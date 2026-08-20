#!/usr/bin/env bash
# Behavioural test for revive_squid() in ../templates/squid-egress-report.sh.j2.
#
# WHY THIS TEST EXISTS: OpenRC keeps a `started` symlink under /run/openrc that
# SURVIVES an abrupt daemon death. After the 2026-08-20 OOM kill, `rc-service
# squid status` still said "started" and `rc-service squid start` answered
# " * WARNING: squid has already been started" and exited 0 WITHOUT launching
# anything. That is exactly the state the watchdog exists to recover from, so a
# revive built on `start` alone silently does nothing, forever.
#
# Stubs `rc-service` and `pgrep` on PATH to emulate that OpenRC behaviour, then
# asserts the daemon is actually running afterwards.
#
# Run:  bash roles/security/tests/test-squid-watchdog-revive.sh
set -u

TPL="$(cd "$(dirname "$0")" && pwd)/../templates/squid-egress-report.sh.j2"
SANDBOX=$(mktemp -d); SCRIPT=$(mktemp); trap 'rm -rf "$SCRIPT" "$SANDBOX"' EXIT
sed -e 's/{{[^}]*}}/900/g' \
    -e "s#^PROM_DIR=.*#PROM_DIR=$SANDBOX#" \
    -e 's#^NOTIFY=.*#NOTIFY=/bin/true#' "$TPL" > "$SCRIPT"

BIN="$SANDBOX/bin"; mkdir -p "$BIN"
export FAKE_STATE="$SANDBOX/openrc-state" FAKE_PROC="$SANDBOX/proc"

cat > "$BIN/rc-service" <<'STUB'
#!/bin/sh
# Emulates OpenRC: `start` is a NO-OP while the service is marked started.
case "$2" in
  zap)   echo stopped > "$FAKE_STATE" ;;
  stop)  echo stopped > "$FAKE_STATE"; rm -f "$FAKE_PROC" ;;
  start)
    if [ "$(cat "$FAKE_STATE" 2>/dev/null)" = "started" ]; then
      echo " * WARNING: squid has already been started" >&2; exit 0
    fi
    echo started > "$FAKE_STATE"; : > "$FAKE_PROC" ;;
esac
exit 0
STUB
cat > "$BIN/pgrep" <<'STUB'
#!/bin/sh
[ -f "$FAKE_PROC" ] && exit 0 || exit 1
STUB
chmod +x "$BIN/rc-service" "$BIN/pgrep"

fail=0
check() { # openrc_state  expected_squid_up  label
  local got
  echo "$1" > "$FAKE_STATE"; rm -f "$FAKE_PROC"
  got=$(PATH="$BIN:$PATH" _REVIVE_POLL=2 bash "$SCRIPT" --revive-only)
  if [ "$got" = "$2" ]; then
    printf 'ok    %-56s squid_up=%s\n' "$3" "$got"
  else
    printf 'FAIL  %-56s expected=%s got=%q\n' "$3" "$2" "$got"; fail=1
  fi
}

check started 1 "STALE OpenRC state (post-OOM) -> revived anyway"
check stopped 1 "cleanly stopped -> revived"

if [ "$fail" = 0 ]; then echo "ALL PASS"; else echo "SOME FAILED"; exit 1; fi
