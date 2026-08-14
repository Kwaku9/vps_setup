#!/bin/sh
# Remove ONE key from the vault. Textual edit only - a YAML round-trip would
# reformat every key, including multi-line values and the tab-separated line
# that this very key uses.
#
# Environment traps (both hit for real on 2026-08-11): `diff` is NOT installed
# here, so every guard uses sha256sum/grep/awk; `cp` is busybox with no long
# options, so the install is `cat > vault.yml`, preserving mode and ownership.
#
# Never prints the value being removed.
set -eu
cd /ansible
NAME="$1"
TS=$(date +%Y%m%d-%H%M%S)

cp -a vault.yml "vault.yml.bak-delkey-$TS"
echo "backup: vault.yml.bak-delkey-$TS (mode $(stat -c%a vault.yml))"

ansible-vault view vault.yml > /dev/shm/v.yml
BEFORE=$(grep -cE '^[A-Za-z0-9_]+:' /dev/shm/v.yml)
HITS=$(grep -cE "^${NAME}:" /dev/shm/v.yml || true)
echo "occurrences of ${NAME}: $HITS"
[ "$HITS" = "1" ] || { echo "ABORT: expected exactly 1, found $HITS"; rm -f /dev/shm/v.yml; exit 1; }

grep -vE "^${NAME}:" /dev/shm/v.yml > /dev/shm/v2.yml
AFTER=$(grep -cE '^[A-Za-z0-9_]+:' /dev/shm/v2.yml)
echo "keys: $BEFORE -> $AFTER (expect -1)"
[ "$AFTER" -eq $((BEFORE - 1)) ] || { echo "ABORT: key count did not drop by exactly 1"; exit 1; }

# every OTHER line must be untouched
A=$(grep -vE "^${NAME}:" /dev/shm/v.yml | sha256sum | cut -d' ' -f1)
B=$(sha256sum < /dev/shm/v2.yml | cut -d' ' -f1)
[ "$A" = "$B" ] || { echo "ABORT: lines other than ${NAME} changed"; exit 1; }
echo "all other lines byte-identical: OK"

ansible-vault encrypt /dev/shm/v2.yml --output /dev/shm/v2.enc >/dev/null
V=$(ansible-vault view /dev/shm/v2.enc | grep -cE '^[A-Za-z0-9_]+:')
G=$(ansible-vault view /dev/shm/v2.enc | grep -cE "^${NAME}:" || true)
[ "$V" -eq "$AFTER" ] || { echo "ABORT: re-encrypted decrypts to $V keys"; exit 1; }
[ "$G" = "0" ]        || { echo "ABORT: key still present after re-encrypt"; exit 1; }
echo "re-encrypted: $V keys, ${NAME} absent"

cat /dev/shm/v2.enc > vault.yml
rm -f /dev/shm/v.yml /dev/shm/v2.yml /dev/shm/v2.enc
echo "VAULT UPDATED (mode $(stat -c%a vault.yml))"
