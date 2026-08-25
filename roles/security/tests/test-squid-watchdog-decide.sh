#!/usr/bin/env bash
# Truth-table test for should_restart() in ../templates/squid-egress-report.sh.j2.
#
# WHY THE WATCHDOG EXISTS: the 02:00 backup restarts the pod fleet and spikes
# memory. On 2026-08-20 squid was OOM-killed at 02:16:56, crash-looped every ~5s
# until OpenRC gave up, and nothing restarted it — leaving every container's :443
# redirected at a dead port for 10 hours. A dead squid fails CLOSED.
#
# WHY THE RESTART IS PARSE-GATED: a config error must stay DOWN and visible rather
# than flap every 5 minutes. Only an otherwise-healthy squid gets revived.
#
# Renders the Jinja template to a runnable script (PROM_DIR is redirected into a
# sandbox so a failing run can never touch the real textfile collector), then
# drives `--watchdog-decide-only` with injected signals.
#
# Run:  bash roles/security/tests/test-squid-watchdog-decide.sh
set -u

TPL="$(cd "$(dirname "$0")" && pwd)/../templates/squid-egress-report.sh.j2"
SANDBOX=$(mktemp -d); SCRIPT=$(mktemp); trap 'rm -rf "$SCRIPT" "$SANDBOX"' EXIT
sed -e 's/{{[^}]*}}/900/g' \
    -e "s#^PROM_DIR=.*#PROM_DIR=$SANDBOX#" \
    -e 's#^NOTIFY=.*#NOTIFY=/bin/true#' "$TPL" > "$SCRIPT"

fail=0
check() { # WATCHDOG SQUID_UP PARSE_OK  EXPECTED  LABEL
  local got
  got=$(_WATCHDOG=$1 _SQUID_UP=$2 _PARSE_OK=$3 bash "$SCRIPT" --watchdog-decide-only)
  if [ "$got" = "$4" ]; then
    printf 'ok    %-52s restart=%s\n' "$5" "$got"
  else
    printf 'FAIL  %-52s expected=%s got=%q\n' "$5" "$4" "$got"; fail=1
  fi
}

#     W S P  exp  label
check 1 0 1   1   "dead daemon + parsable config -> restart"
check 1 0 0   0   "dead daemon + BROKEN config -> stay down, visible"
check 1 1 1   0   "daemon alive -> no restart"
check 0 0 1   0   "watchdog disabled -> no restart"

if [ "$fail" = 0 ]; then echo "ALL PASS"; else echo "SOME FAILED"; exit 1; fi
