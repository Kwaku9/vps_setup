#!/bin/sh
# Replace exactly one line in the vault: litellm_salt_key.
#
# Textual edit only -- a YAML round-trip would reformat all 129 keys, including
# multi-line private keys and a tab-separated line.
#
# Two environment traps this script exists to survive, both hit for real:
#   * `diff` is NOT installed here. An earlier version used it, got "0 changed
#     lines" from a command that never ran, and concluded nothing changed.
#     Every guard below uses sha256sum/grep/awk only.
#   * `cp` is busybox and rejects long options like --preserve=mode. The final
#     install is `cat > vault.yml`, which replaces content in place and leaves
#     the existing mode and ownership untouched.
#
# The stored value is QUOTED, so the replacement is written quoted too, and
# every hash comparison strips quotes so it compares values, not syntax.
set -eu
cd /ansible
TS=$(date +%Y%m%d-%H%M%S)
NEW=$(cat /dev/shm/candidate-salt)
[ -n "$NEW" ] || { echo "ABORT: candidate salt is empty"; exit 1; }

unq() { cut -d' ' -f2- | tr -d '"'"'"'\n'; }   # strip quotes + newline

cp -a vault.yml "vault.yml.bak-salt-$TS"
echo "backup: vault.yml.bak-salt-$TS  (mode $(stat -c%a vault.yml))"

ansible-vault view vault.yml > /dev/shm/v.yml
BEFORE=$(grep -cE '^[A-Za-z0-9_]+:' /dev/shm/v.yml)
HITS=$(grep -cE '^litellm_salt_key:' /dev/shm/v.yml)
[ "$HITS" = "1" ] || { echo "ABORT: expected 1 litellm_salt_key line, found $HITS"; exit 1; }

awk -v new="$NEW" '/^litellm_salt_key:/ { print "litellm_salt_key: \"" new "\""; next } { print }' \
    /dev/shm/v.yml > /dev/shm/v2.yml

OLDH=$(grep '^litellm_salt_key:' /dev/shm/v.yml  | unq | sha256sum | cut -c1-16)
NEWH=$(grep '^litellm_salt_key:' /dev/shm/v2.yml | unq | sha256sum | cut -c1-16)
CANDH=$(printf %s "$NEW" | sha256sum | cut -c1-16)
echo "salt value: $OLDH -> $NEWH (candidate $CANDH)"
[ "$OLDH" != "$NEWH" ]  || { echo "ABORT: salt did not change"; exit 1; }
[ "$NEWH"  = "$CANDH" ] || { echo "ABORT: salt is not the candidate"; exit 1; }

A=$(grep -v '^litellm_salt_key:' /dev/shm/v.yml  | sha256sum | cut -d' ' -f1)
B=$(grep -v '^litellm_salt_key:' /dev/shm/v2.yml | sha256sum | cut -d' ' -f1)
[ "$A" = "$B" ] || { echo "ABORT: lines other than the salt changed"; exit 1; }
AFTER=$(grep -cE '^[A-Za-z0-9_]+:' /dev/shm/v2.yml)
[ "$BEFORE" = "$AFTER" ] || { echo "ABORT: key count $BEFORE -> $AFTER"; exit 1; }
echo "all other lines byte-identical; key count held at $AFTER"

ansible-vault encrypt /dev/shm/v2.yml --output /dev/shm/v2.enc >/dev/null
V=$(ansible-vault view /dev/shm/v2.enc | grep -cE '^[A-Za-z0-9_]+:')
RT=$(ansible-vault view /dev/shm/v2.enc | grep '^litellm_salt_key:' | unq | sha256sum | cut -c1-16)
[ "$V" = "$BEFORE" ] || { echo "ABORT: re-encrypted decrypts to $V keys"; exit 1; }
[ "$RT" = "$CANDH" ]  || { echo "ABORT: round-trip salt mismatch"; exit 1; }
echo "re-encrypted: $V keys, salt round-trips"

cat /dev/shm/v2.enc > vault.yml          # in place: preserves mode/ownership
rm -f /dev/shm/v.yml /dev/shm/v2.yml /dev/shm/v2.enc
echo "VAULT UPDATED (mode now $(stat -c%a vault.yml))"
