#!/usr/bin/env bash
# fix-cloudfront-baseline.sh — bring a CloudFront distribution up to the
# external security baseline.
#
#   ./fix-cloudfront-baseline.sh <domain>            # DRY RUN (default)
#   ./fix-cloudfront-baseline.sh <domain> --apply    # actually change things
#
# Fixes two findings (docs/EXTERNAL-ATTACK-SURFACE.md):
#   F2  — custom error responses rewrite 403/404 to HTTP 200 for every path
#   F10 — no security response headers
#
# WHY F2 MATTERS (§3.6): returning 200 for paths that do not exist means you
# cannot distinguish an attacker probing /wp-login.php from a real user. It
# blinds your own detection, lets search engines index infinite junk, and makes
# every junk path a year-long edge cache entry.
#
# larougebrows.com already does this correctly on the same CloudFront+S3 stack —
# it serves the SPA shell but preserves the 404 status. It is the reference.
#
# REQUIRES: aws cli configured with cloudfront:GetDistributionConfig,
#           cloudfront:UpdateDistribution, cloudfront:CreateResponseHeadersPolicy

set -euo pipefail

DOMAIN="${1:-}"; APPLY=0
[[ "${2:-}" == "--apply" ]] && APPLY=1
[[ -z "$DOMAIN" ]] && { echo "usage: $0 <domain> [--apply]" >&2; exit 2; }
command -v aws >/dev/null || { echo "aws cli not found" >&2; exit 2; }
command -v jq  >/dev/null || { echo "jq not found" >&2; exit 2; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
[[ $APPLY -eq 0 ]] && printf '\033[33m*** DRY RUN — nothing will be modified. Re-run with --apply. ***\033[0m\n'

# ── Locate the distribution serving this domain ────────────────────────────
say "[1] Locating CloudFront distribution for $DOMAIN"
DIST_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?contains(Aliases.Items || \`[]\`, '$DOMAIN')].Id | [0]" \
  --output text 2>/dev/null)

if [[ -z "$DIST_ID" || "$DIST_ID" == "None" ]]; then
  echo "  No distribution found with alias '$DOMAIN'." >&2
  echo "  Check credentials/region, or that the alias is on the distribution." >&2
  exit 1
fi
echo "  distribution: $DIST_ID"

aws cloudfront get-distribution-config --id "$DIST_ID" > "$WORK/dist.json"
ETAG=$(jq -r '.ETag' "$WORK/dist.json")
jq '.DistributionConfig' "$WORK/dist.json" > "$WORK/config.json"
echo "  etag: $ETAG"

# ── Report current error-response behaviour ────────────────────────────────
say "[2] Current custom error responses"
jq -r '
  if (.CustomErrorResponses.Quantity // 0) == 0 then "  (none configured)"
  else .CustomErrorResponses.Items[]
       | "  \(.ErrorCode) -> \(.ResponsePagePath // "-")  status=\(.ResponseCode // "unchanged")  ttl=\(.ErrorCachingMinTTL // "-")"
  end' "$WORK/config.json"

BAD=$(jq '[ .CustomErrorResponses.Items // []
           | .[] | select((.ErrorCode==403 or .ErrorCode==404) and .ResponseCode=="200") ] | length' "$WORK/config.json")

if [[ "$BAD" -gt 0 ]]; then
  echo
  echo "  \033[31mFINDING F2 CONFIRMED\033[0m: $BAD rule(s) rewrite 403/404 to HTTP 200."
  echo "  Every nonexistent path returns 200. This blinds probe detection."
else
  echo
  echo "  No 200-rewrite rules found — F2 may already be fixed here."
fi

# ── Build the corrected error-response block ───────────────────────────────
# Keep serving /index.html (SPA deep links still work) but return the TRUE
# status code. A SPA router that needs to handle unknown client-side routes
# should render its own not-found view — the HTTP status must stay honest.
say "[3] Corrected error responses (what will be written)"
jq '.CustomErrorResponses = {
      "Quantity": 2,
      "Items": [
        { "ErrorCode": 403, "ResponsePagePath": "/index.html",
          "ResponseCode": "404", "ErrorCachingMinTTL": 10 },
        { "ErrorCode": 404, "ResponsePagePath": "/index.html",
          "ResponseCode": "404", "ErrorCachingMinTTL": 10 }
      ]
    }' "$WORK/config.json" > "$WORK/config.new.json"

jq -r '.CustomErrorResponses.Items[]
       | "  \(.ErrorCode) -> \(.ResponsePagePath)  status=\(.ResponseCode)  ttl=\(.ErrorCachingMinTTL)"' \
  "$WORK/config.new.json"
echo
echo "  NOTE: ErrorCachingMinTTL is lowered to 10s. The default (300s) means a"
echo "  transient origin error gets cached as a 404 for five minutes."

# ── Security response headers policy ───────────────────────────────────────
say "[4] Security headers policy"
POLICY_NAME="baseline-security-headers"
POLICY_ID=$(aws cloudfront list-response-headers-policies --type custom \
  --query "ResponseHeadersPolicyList.Items[?ResponseHeadersPolicy.ResponseHeadersPolicyConfig.Name=='$POLICY_NAME'].ResponseHeadersPolicy.Id | [0]" \
  --output text 2>/dev/null || echo "")

cat > "$WORK/headers-policy.json" <<'JSON'
{
  "Name": "baseline-security-headers",
  "Comment": "External security baseline - see docs/EXTERNAL-ATTACK-SURFACE.md",
  "SecurityHeadersConfig": {
    "StrictTransportSecurity": {
      "Override": true, "AccessControlMaxAgeSec": 31536000,
      "IncludeSubdomains": true, "Preload": true
    },
    "ContentTypeOptions":  { "Override": true },
    "FrameOptions":        { "Override": true, "FrameOption": "DENY" },
    "ReferrerPolicy":      { "Override": true, "ReferrerPolicy": "strict-origin-when-cross-origin" },
    "XSSProtection":       { "Override": true, "Protection": true, "ModeBlock": true },
    "ContentSecurityPolicy": {
      "Override": true,
      "ContentSecurityPolicy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' https:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
    }
  },
  "CustomHeadersConfig": {
    "Quantity": 1,
    "Items": [
      { "Header": "Permissions-Policy",
        "Value": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()",
        "Override": true }
    ]
  },
  "RemoveHeadersConfig": {
    "Quantity": 2,
    "Items": [ { "Header": "Server" }, { "Header": "X-Powered-By" } ]
  }
}
JSON

if [[ -n "$POLICY_ID" && "$POLICY_ID" != "None" ]]; then
  echo "  reusing existing policy '$POLICY_NAME' ($POLICY_ID)"
else
  echo "  policy '$POLICY_NAME' does not exist yet — will be created"
  echo "  it sets: HSTS, CSP, X-Frame-Options DENY, nosniff, Referrer-Policy,"
  echo "           Permissions-Policy; and REMOVES Server + X-Powered-By"
fi

# ── Apply ──────────────────────────────────────────────────────────────────
if [[ $APPLY -eq 0 ]]; then
  say "DRY RUN COMPLETE"
  cat <<EOF
  Nothing was changed. To apply:

      $0 $DOMAIN --apply

  Then wait for the distribution to redeploy (~5-15 min) and verify:

      ./scripts/verify-domain-baseline.sh $DOMAIN

  Expect: 'nonexistent path returns 404' and 'HSTS present'.
EOF
  exit 0
fi

say "[5] Applying"

if [[ -z "$POLICY_ID" || "$POLICY_ID" == "None" ]]; then
  POLICY_ID=$(aws cloudfront create-response-headers-policy \
    --response-headers-policy-config "file://$WORK/headers-policy.json" \
    --query 'ResponseHeadersPolicy.Id' --output text)
  echo "  created response headers policy: $POLICY_ID"
fi

# Attach the policy to the default cache behaviour.
jq --arg pid "$POLICY_ID" \
   '.DefaultCacheBehavior.ResponseHeadersPolicyId = $pid' \
   "$WORK/config.new.json" > "$WORK/config.final.json"

aws cloudfront update-distribution \
  --id "$DIST_ID" \
  --if-match "$ETAG" \
  --distribution-config "file://$WORK/config.final.json" \
  --query 'Distribution.Status' --output text

cat <<EOF

  Distribution updated. Redeployment takes ~5-15 minutes.

  Verify once Status=Deployed:
      ./scripts/verify-domain-baseline.sh $DOMAIN

  If the SPA now 404s on legitimate deep links, the app's client-side router
  needs to render its own not-found view — do NOT revert to returning 200.
EOF
