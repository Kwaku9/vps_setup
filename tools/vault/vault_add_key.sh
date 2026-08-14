#!/bin/sh
# Append ONE new key to the vault. Textual edit only - a YAML round-trip would
# reformat all 139 keys including multi-line values and a tab-separated line.
#
# Environment traps this survives (both hit for real on 2026-08-11):
#   * `diff` is NOT installed here - all guards use sha256sum/grep/awk.
#   * `cp` is busybox, no long options - install is `cat > vault.yml`, which
#     replaces content in place and preserves mode/ownership.
set -eu
cd /ansible
NAME="$1"
TS=$(date +%Y%m%d-%H%M%S)
VAL=$(cat /dev/shm/newkey-value)
[ -n "$VAL" ] || { echo "ABORT: value is empty"; exit 1; }

cp -a vault.yml "vault.yml.bak-addkey-$TS"
echo "backup: vault.yml.bak-addkey-$TS (mode $(stat -c%a vault.yml))"

ansible-vault view vault.yml > /dev/shm/v.yml
BEFORE=$(grep -cE '^[A-Za-z0-9_]+:' /dev/shm/v.yml)
if grep -qE "^${NAME}:" /dev/shm/v.yml; then
  echo "ABORT: key '$NAME' already exists - this script only ADDS"; rm -f /dev/shm/v.yml; exit 1
fi

cp /dev/shm/v.yml /dev/shm/v2.yml
printf '%s: "%s"\n' "$NAME" "$VAL" >> /dev/shm/v2.yml

AFTER=$(grep -cE '^[A-Za-z0-9_]+:' /dev/shm/v2.yml)
echo "keys: $BEFORE -> $AFTER (expect +1)"
[ "$AFTER" -eq $((BEFORE + 1)) ] || { echo "ABORT: key count did not increase by exactly 1"; exit 1; }

# every pre-existing line must be untouched
A=$(sha256sum < /dev/shm/v.yml | cut -d' ' -f1)
B=$(head -n "$(wc -l < /dev/shm/v.yml)" /dev/shm/v2.yml | sha256sum | cut -d' ' -f1)
[ "$A" = "$B" ] || { echo "ABORT: existing content changed"; exit 1; }
echo "all pre-existing lines byte-identical: OK"

ansible-vault encrypt /dev/shm/v2.yml --output /dev/shm/v2.enc >/dev/null
V=$(ansible-vault view /dev/shm/v2.enc | grep -cE '^[A-Za-z0-9_]+:')
RT=$(ansible-vault view /dev/shm/v2.enc | grep "^${NAME}:" | cut -d' ' -f2- | tr -d '"' | tr -d '\n' | sha256sum | cut -c1-16)
EXP=$(printf %s "$VAL" | sha256sum | cut -c1-16)
[ "$V" -eq "$AFTER" ] || { echo "ABORT: re-encrypted decrypts to $V keys"; exit 1; }
[ "$RT" = "$EXP" ]    || { echo "ABORT: round-trip value mismatch"; exit 1; }
echo "re-encrypted: $V keys, new value round-trips"

cat /dev/shm/v2.enc > vault.yml
rm -f /dev/shm/v.yml /dev/shm/v2.yml /dev/shm/v2.enc /dev/shm/newkey-value
echo "VAULT UPDATED (mode $(stat -c%a vault.yml))"
