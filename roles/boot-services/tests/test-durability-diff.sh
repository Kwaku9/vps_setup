#!/usr/bin/env bash
# Tests the comparison logic of verify-boot-durability against fixture snapshots.
# The live-probing half needs a real host; the DIFF half is where the bugs hide
# (missing service reported as present, ordering treated as a difference, an
# extra service masking a missing one), so that is what is tested here.
#
# Run:  bash roles/boot-services/tests/test-durability-diff.sh
set -u
SCRIPT="$(cd "$(dirname "$0")" && pwd)/../files/verify-boot-durability.sh"
SB=$(mktemp -d); trap 'rm -rf "$SB"' EXIT
fail=0

check() { # before_list  after_list  expected_exit  label
  printf '%s\n' $1 > "$SB/before"; printf '%s\n' $2 > "$SB/after"
  out=$(bash "$SCRIPT" --diff "$SB/before" "$SB/after" 2>&1); rc=$?
  if [ "$rc" = "$3" ]; then printf 'ok    %-50s exit=%s\n' "$4" "$rc"
  else printf 'FAIL  %-50s expected exit=%s got=%s\n%s\n' "$4" "$3" "$rc" "$out"; fail=1; fi
}

check "a b c"   "a b c"     0 "identical -> pass"
check "a b c"   "c b a"     0 "reordered -> pass (order is not drift)"
check "a b c"   "a c"       1 "one service missing -> FAIL"
check "a b c"   "a b c d"   0 "extra service -> pass (not a loss)"
check "a b c"   "a c d"     1 "extra must NOT mask a missing one -> FAIL"
check "a b c"   ""          1 "everything gone -> FAIL"

[ "$fail" = 0 ] && echo "ALL PASS" || { echo "SOME FAILED"; exit 1; }
