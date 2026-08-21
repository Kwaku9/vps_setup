#!/usr/bin/env bash
# verify-domain-baseline.sh — assert the external security baseline for a domain.
#
# Usage:
#   ./verify-domain-baseline.sh <domain> [--since YYYY-MM-DD] [--deception-apex] [--quiet]
#
#   --since YYYY-MM-DD  Wildcard-cutover date. Any per-hostname certificate issued
#                       on/after this date is a REGRESSION (the CT leak came back).
#                       Without it, per-host certs are reported as INFO only.
#   --deception-apex    The apex is a honeypot and is SUPPOSED to emit fake
#                       version headers. Suppresses the version-disclosure failure
#                       for the apex only. (aicortex.cloud)
#   --strict-404        Also require EXTENSIONLESS nonexistent paths to return
#                       non-200. Correct for static sites; will fail a genuine
#                       SPA, where the client-side router owns unknown routes.
#   --quiet             Only print failures and the summary.
#
# Exit codes: 0 = all pass, 1 = one or more FAIL, 2 = usage/dependency error.
#
# Every assertion that can have one is paired with a CONTROL that must fail.
# A check whose control also passes proves nothing and is reported as BROKEN.
#
# See docs/EXTERNAL-ATTACK-SURFACE.md for what each control defends against.

set -uo pipefail

DOMAIN=""; SINCE=""; DECEPTION_APEX=0; QUIET=0; STRICT_404=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --since)          SINCE="${2:-}"; shift 2 ;;
    --deception-apex) DECEPTION_APEX=1; shift ;;
    --strict-404)     STRICT_404=1; shift ;;
    --quiet)          QUIET=1; shift ;;
    -h|--help)        sed -n '2,20p' "$0"; exit 0 ;;
    *)                DOMAIN="$1"; shift ;;
  esac
done
[[ -z "$DOMAIN" ]] && { echo "usage: $0 <domain> [--since YYYY-MM-DD] [--deception-apex] [--quiet]" >&2; exit 2; }

for dep in dig curl openssl; do
  command -v "$dep" >/dev/null || { echo "missing dependency: $dep" >&2; exit 2; }
done
HAVE_JQ=1; command -v jq >/dev/null || HAVE_JQ=0

PASS=0; FAIL=0; WARN=0; BROKEN=0
C_G=$'\033[32m'; C_R=$'\033[31m'; C_Y=$'\033[33m'; C_M=$'\033[35m'; C_0=$'\033[0m'
[[ -t 1 ]] || { C_G=""; C_R=""; C_Y=""; C_M=""; C_0=""; }

ok()     { PASS=$((PASS+1)); [[ $QUIET -eq 1 ]] || printf '  %sPASS%s  %s\n' "$C_G" "$C_0" "$1"; }
bad()    { FAIL=$((FAIL+1)); printf '  %sFAIL%s  %s\n' "$C_R" "$C_0" "$1"; [[ -n "${2:-}" ]] && printf '        ↳ %s\n' "$2"; }
warn()   { WARN=$((WARN+1)); [[ $QUIET -eq 1 ]] || printf '  %sWARN%s  %s\n' "$C_Y" "$C_0" "$1"; }
broken() { BROKEN=$((BROKEN+1)); printf '  %sBROKEN%s %s\n' "$C_M" "$C_0" "$1"; }
sec()    { [[ $QUIET -eq 1 ]] || printf '\n%s\n' "$1"; }

echo "═══ external baseline: $DOMAIN ═══"
[[ -n "$SINCE" ]] && echo "    wildcard cutover: $SINCE"

# ── 1. Email authentication ────────────────────────────────────────────────
sec "[1] Email authentication (anti-spoofing / T1566)"

SPF=$(dig +short TXT "$DOMAIN" | tr -d '"' | grep -i '^v=spf1' | head -1)
if [[ -z "$SPF" ]]; then
  bad "no SPF record" "domain is freely spoofable; publish at minimum \"v=spf1 -all\""
elif grep -qi '+all' <<<"$SPF"; then
  bad "SPF ends in +all (authorises the entire internet)" "$SPF"
elif grep -qi '~all' <<<"$SPF"; then
  warn "SPF softfail (~all) — acceptable only during rollout; target -all"
elif grep -qi -- '-all' <<<"$SPF"; then
  ok "SPF hardfail (-all)"
else
  warn "SPF present but no explicit all-qualifier: $SPF"
fi

DMARC=$(dig +short TXT "_dmarc.$DOMAIN" | tr -d '"' | grep -i '^v=DMARC1' | head -1)
if [[ -z "$DMARC" ]]; then
  bad "no DMARC record" "SPF alone does NOT protect the visible From: header"
else
  POL=$(grep -oiE 'p=[a-z]+' <<<"$DMARC" | head -1 | cut -d= -f2 | tr 'A-Z' 'a-z')
  case "$POL" in
    reject)     ok "DMARC p=reject" ;;
    quarantine) warn "DMARC p=quarantine — ramp to reject once rua reports are clean" ;;
    none)       bad "DMARC p=none (monitor-only, enforces nothing)" "$DMARC" ;;
    *)          bad "DMARC present but policy unparseable" "$DMARC" ;;
  esac
  grep -qi 'rua=' <<<"$DMARC" && ok "DMARC rua= reporting configured" \
                              || warn "no rua= — you get no visibility into spoofing attempts"
  grep -qiE 'adkim=s' <<<"$DMARC" && ok "strict DKIM alignment (adkim=s)" || true
fi

# CONTROL: probe a selector that cannot legitimately exist.
#
# Three distinct outcomes, and conflating them is why this check was wrong at
# first. A domain running the baseline publishes a *._domainkey NULL record on
# purpose, so "it resolved" is not by itself a failure — what matters is WHAT it
# resolved to. A wildcard that hands out a real public key would let an attacker
# claim any selector they like.
CTRL_DKIM=$(dig +short TXT "nonexistent-selector-9z8x7q._domainkey.$DOMAIN" | tr -d '"' | head -1)
if [[ -z "$CTRL_DKIM" ]]; then
  ok "no DKIM key published for an arbitrary selector"
elif [[ "$CTRL_DKIM" =~ ^v=DKIM1\;?[[:space:]]*p=[[:space:]]*$ ]]; then
  ok "wildcard DKIM null record revokes all unlisted selectors"
elif [[ "$CTRL_DKIM" =~ p=[A-Za-z0-9+/] ]]; then
  bad "a REAL DKIM key is served for an arbitrary selector" \
      "any selector an attacker picks will validate — remove the wildcard key"
else
  broken "control inconclusive: bogus DKIM selector returned an unrecognised value"
fi

# ── 2. Certificate issuance control ────────────────────────────────────────
sec "[2] Certificate issuance control (T1588.004 / T1584.001)"

CAA_OUT=$(dig +short CAA "$DOMAIN")
if [[ -z "$CAA_OUT" ]]; then
  bad "no CAA records" "any of ~150 public CAs may issue for this domain"
else
  ok "CAA present ($(grep -c issue <<<"$CAA_OUT") issue directive(s))"
  grep -q issuewild <<<"$CAA_OUT" && ok "CAA issuewild set" \
                                  || warn "no issuewild — some CAs then refuse wildcards, breaking renewal"
  grep -q iodef <<<"$CAA_OUT" && ok "CAA iodef set (CAs report attempted violations)" \
                              || warn "no iodef — you lose early warning of mis-issuance attempts"
fi

if [[ -z "$(dig +short DS "$DOMAIN")" ]]; then
  warn "no DNSSEC DS record — DNS answers are unauthenticated (T1557)"
else
  ok "DNSSEC DS present"
fi

# ── 3. CT-log hygiene — the regression test that matters most ──────────────
sec "[3] Certificate Transparency hygiene (T1596.003)"

if [[ $HAVE_JQ -eq 0 ]]; then
  warn "jq not installed — skipping CT enumeration"
else
  CT=$(curl -s --max-time 60 \
    "https://api.certspotter.com/v1/issuances?domain=${DOMAIN}&include_subdomains=true&expand=dns_names" 2>/dev/null)
  if [[ -z "$CT" ]] || ! jq -e 'type=="array"' >/dev/null 2>&1 <<<"$CT"; then
    warn "CT API unavailable or rate-limited — could not verify (re-run later)"
  else
    # Per-hostname = any cert whose SANs are neither the apex nor the wildcard.
    PERHOST=$(jq -r --arg d "$DOMAIN" --arg since "${SINCE:-0000-00-00}" '
      .[] | select(.not_before[0:10] >= $since)
          | select([.dns_names[] | select(. != $d and . != ("*." + $d))] | length > 0)
          | "\(.not_before[0:10])  \([.dns_names[]] | join(","))"
    ' <<<"$CT" 2>/dev/null | sort -u)
    NAMES=$(jq -r '.[].dns_names[]' <<<"$CT" 2>/dev/null | tr 'A-Z' 'a-z' | sed 's/^\*\.//' | sort -u | grep -v "^${DOMAIN}$" || true)
    NCOUNT=$(grep -c . <<<"$NAMES" 2>/dev/null || echo 0)

    if [[ -z "$PERHOST" ]]; then
      if [[ -n "$SINCE" ]]; then ok "no per-hostname certificates issued since $SINCE"
      else ok "no per-hostname certificates found"; fi
    else
      if [[ -n "$SINCE" ]]; then
        bad "per-hostname certificate(s) issued since $SINCE — CT LEAK REGRESSION" \
            "$(head -5 <<<"$PERHOST" | tr '\n' ' | ')"
      else
        warn "$(grep -c . <<<"$PERHOST") per-hostname cert(s) in CT (pass --since to enforce)"
      fi
    fi
    [[ $NCOUNT -gt 0 ]] && warn "$NCOUNT distinct hostname(s) publicly enumerable via CT" || true
  fi
fi

# ── 4. DNS enumeration resistance ──────────────────────────────────────────
sec "[4] DNS enumeration resistance (T1590.002)"

XFR_OK=1
for ns in $(dig +short NS "$DOMAIN"); do
  if timeout 8 dig AXFR "$DOMAIN" "@$ns" +short 2>&1 | grep -qE '^[a-zA-Z0-9_.-]+\.\s+[0-9]+\s+IN'; then
    bad "zone transfer ALLOWED from $ns" "entire zone is downloadable by anyone"; XFR_OK=0
  fi
done
[[ $XFR_OK -eq 1 ]] && ok "zone transfer refused by all nameservers"

if [[ -n "$(dig +short A "nonexistent-9z8x7q-control.$DOMAIN")" ]]; then
  bad "wildcard DNS present" "every guessed hostname resolves; confirms attacker guesses for free"
else
  ok "no wildcard DNS"
fi

# ── 5. TLS ─────────────────────────────────────────────────────────────────
sec "[5] TLS posture"

for v in tls1 tls1_1; do
  case "$v" in tls1) label="TLS 1.0" ;; tls1_1) label="TLS 1.1" ;; esac
  if echo | timeout 12 openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" "-$v" 2>&1 \
       | grep -qE 'Cipher is (TLS|ECDHE|AES|DHE)'; then
    bad "$label accepted" "deprecated protocol enables downgrade (T1557)"
  else
    ok "$label rejected"
  fi
done

EXP=$(echo | timeout 15 openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null \
      | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [[ -n "$EXP" ]]; then
  EXP_S=$(date -d "$EXP" +%s 2>/dev/null || echo 0)
  NOW_S=$(date +%s)
  if [[ "$EXP_S" -gt 0 ]]; then
    DAYS=$(( (EXP_S - NOW_S) / 86400 ))
    if   [[ $DAYS -lt 0  ]]; then bad "certificate EXPIRED ($EXP)"
    elif [[ $DAYS -lt 14 ]]; then bad "certificate expires in ${DAYS}d ($EXP)"
    elif [[ $DAYS -lt 30 ]]; then warn "certificate expires in ${DAYS}d"
    else ok "certificate valid for ${DAYS}d"; fi
  fi
else
  warn "could not read certificate expiry"
fi

# ── 6. HTTP response hygiene ───────────────────────────────────────────────
sec "[6] HTTP response hygiene (T1592.002 / T1595.003)"

HDRS=$(curl -sSI --max-time 20 "https://$DOMAIN" 2>/dev/null)
if [[ -z "$HDRS" ]]; then
  warn "no HTTPS response from apex — skipping header checks"
else
  hdr_has() { grep -qi "^$1:" <<<"$HDRS"; }

  hdr_has strict-transport-security && ok "HSTS present" \
    || bad "no HSTS" "first-contact downgrade remains possible (T1557)"
  hdr_has x-content-type-options && ok "X-Content-Type-Options present" \
    || warn "no X-Content-Type-Options (MIME sniffing → stored XSS)"
  hdr_has x-frame-options || grep -qi 'frame-ancestors' <<<"$HDRS" \
    && ok "framing controlled" || warn "no X-Frame-Options / frame-ancestors (clickjacking, T1185)"
  hdr_has referrer-policy && ok "Referrer-Policy present" || warn "no Referrer-Policy"
  hdr_has content-security-policy && ok "CSP present" \
    || warn "no CSP — author in report-only first, then enforce"

  VER=$(grep -iE '^(x-powered-by|x-aspnet-version|x-generator):' <<<"$HDRS" | tr -d '\r')
  if [[ -n "$VER" ]]; then
    if [[ $DECEPTION_APEX -eq 1 ]]; then
      ok "version headers present but apex is a declared honeypot (intentional deception)"
    else
      bad "version-disclosure header on apex" "$(head -1 <<<"$VER")"
    fi
  else
    [[ $DECEPTION_APEX -eq 1 ]] \
      && warn "apex declared as honeypot but emits no version headers — deception may be broken" \
      || ok "no version-disclosure headers"
  fi
fi

# 404 semantics.
#
# Two DIFFERENT probes, because they mean different things on a single-page app:
#
#   file-like  (/x.php, /.env)  — must ALWAYS 404. A 200 here means the edge is
#                                 swallowing misses and serving the app shell for
#                                 anything, which is the real finding: it blinds
#                                 probe detection and caches junk paths.
#   extensionless (/xyz)        — on an SPA this legitimately returns the shell
#                                 with 200, because the client-side router owns
#                                 unknown routes and the edge cannot know which
#                                 ones exist. Only enforced with --strict-404.
#
# Conflating the two produced a false FAIL against a correctly-configured SPA,
# which is worse than useless — a check nobody trusts gets ignored.
REAL=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/" 2>/dev/null)
FILEISH=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/zz-control-$RANDOM.php" 2>/dev/null)
EXTLESS=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/zz-control-$RANDOM$RANDOM" 2>/dev/null)

if [[ -z "$FILEISH" || "$FILEISH" == "000" ]]; then
  warn "could not probe 404 behaviour"
elif [[ ! "$REAL" =~ ^(200|301|302)$ ]]; then
  broken "control failed: site root returned $REAL — 404 checks inconclusive"
elif [[ "$FILEISH" == "200" ]]; then
  bad "nonexistent FILE path returns HTTP 200" \
      "edge is serving the app shell for any path — blinds probe detection, caches junk"
else
  ok "nonexistent file path returns $FILEISH (root returns $REAL)"
  if [[ "$EXTLESS" == "200" ]]; then
    if [[ $STRICT_404 -eq 1 ]]; then
      bad "extensionless nonexistent path returns 200" \
          "--strict-404 requires the edge to know its own routes"
    else
      warn "extensionless paths return 200 (normal for an SPA; use --strict-404 to enforce)"
    fi
  else
    ok "extensionless nonexistent path returns $EXTLESS"
  fi
fi

# ── Summary ────────────────────────────────────────────────────────────────
printf '\n═══ %s: %s%d pass%s  %s%d fail%s  %s%d warn%s' \
  "$DOMAIN" "$C_G" "$PASS" "$C_0" "$C_R" "$FAIL" "$C_0" "$C_Y" "$WARN" "$C_0"
[[ $BROKEN -gt 0 ]] && printf '  %s%d BROKEN-CONTROL%s' "$C_M" "$BROKEN" "$C_0"
printf ' ═══\n'

[[ $BROKEN -gt 0 ]] && { echo "A control test did not fail as required — treat results as unreliable." >&2; exit 1; }
[[ $FAIL   -gt 0 ]] && exit 1
exit 0
