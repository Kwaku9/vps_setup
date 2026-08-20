#!/usr/bin/env bash
# Truth-table test for decide_up() in ../templates/squid-egress-report.sh.j2.
#
# Renders the Jinja template to a runnable script (the only Jinja expression is the
# STALE_AFTER default, which decide_up does not use), then drives `--decide-only`
# with injected signals and asserts the published squid_intercept_up.
#
# Run:  bash roles/security/tests/test-squid-intercept-decide.sh
# This FAILS until decide_up() is implemented (stub echoes nothing).
set -u

TPL="$(cd "$(dirname "$0")" && pwd)/../templates/squid-egress-report.sh.j2"
SANDBOX=$(mktemp -d); SCRIPT=$(mktemp); trap 'rm -rf "$SCRIPT" "$SANDBOX"' EXIT
# --decide-only exits before any probing/writing, but redirect PROM_DIR and stub
# out NOTIFY anyway: a red run must never touch the real textfile collector or
# fire a real Telegram alert if a future edit lets it fall through.
sed -e 's/{{[^}]*}}/900/g' \
    -e "s#^PROM_DIR=.*#PROM_DIR=$SANDBOX#" \
    -e 's#^NOTIFY=.*#NOTIFY=/bin/true#' "$TPL" > "$SCRIPT"

fail=0
check() { # FRESH SQUID_UP RULE_PRESENT PKTS_ADVANCED  EXPECTED  LABEL
  local got
  got=$(_FRESH=$1 _SQUID_UP=$2 _RULE_PRESENT=$3 _PKTS_ADVANCED=$4 bash "$SCRIPT" --decide-only)
  if [ "$got" = "$5" ]; then
    printf 'ok    %-46s up=%s\n' "$6" "$got"
  else
    printf 'FAIL  %-46s expected=%s got=%q\n' "$6" "$5" "$got"; fail=1
  fi
}

#     F S R P  exp  label
check 0 0 1 0   0   "squid daemon dead -> DOWN"
check 0 1 0 0   0   "REDIRECT rule missing -> DOWN (reboot bypass)"
check 0 0 0 0   0   "daemon dead + no rule -> DOWN"
check 1 1 1 1   1   "fresh log + counter advancing -> UP"
check 1 1 1 0   1   "fresh log -> UP"
check 0 1 1 1   1   "stale log but counter advancing -> UP"
check 0 1 1 0   1   "idle window, plumbing intact -> UP (no page on idle)"

if [ "$fail" = 0 ]; then echo "ALL PASS"; else echo "SOME FAILED"; exit 1; fi
