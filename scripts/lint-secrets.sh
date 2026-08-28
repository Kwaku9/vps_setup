#!/bin/sh
# lint-secrets.sh — block identifiers and credentials from entering the repo.
#
# WHY
#   This repository is PUBLIC. Anything committed here is world-readable
#   immediately and stays in the history even after deletion. git-crypt protects
#   all.yml and the vaults; everything else is plaintext to the world.
#
#   A Cloudflare account id reached roles/cloudflare/README.md and
#   tools/yt-transcript-worker/wrangler.toml this way, and is in four historical
#   commits. Not a credential on its own, but it is the account half of every R2
#   API call — no reason for it to be public.
#
# SCOPE
#   git-crypt'd paths are skipped: they are ENCRYPTED at rest in git, so secrets
#   there are correct by design. Scanning them would fire on every commit and
#   train everyone to pass --no-verify.
set -eu
cd "$(dirname "$0")/.."

FILES=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || git ls-files)
[ -n "$FILES" ] || { echo "  secrets: nothing to scan"; exit 0; }

CRYPT_PATTERNS=$(grep -E 'filter=git-crypt' .gitattributes 2>/dev/null | awk '{print $1}' || true)

hits=0
for f in $FILES; do
  [ -f "$f" ] || continue
  skip=0
  for pat in $CRYPT_PATTERNS; do
    case "$f" in $pat) skip=1; break;; esac
  done
  [ "$skip" = 1 ] && continue
  case "$f" in scripts/lint-secrets.sh) continue;; esac

  # Cloudflare account id: 32 hex in an R2 endpoint or an account_id assignment
  if grep -qE '\b[0-9a-f]{32}\.r2\.cloudflarestorage\.com|account_id[[:space:]]*=[[:space:]]*"?[0-9a-f]{32}' "$f" 2>/dev/null; then
    echo "  CLOUDFLARE ACCOUNT ID   $f"; hits=$((hits+1))
  fi
  # Telegram bot token: <digits>:<35 base64-ish>
  if grep -qE 'bot[0-9]{8,12}:[A-Za-z0-9_-]{30,}' "$f" 2>/dev/null; then
    echo "  TELEGRAM BOT TOKEN      $f"; hits=$((hits+1))
  fi
  # AWS / R2 secret access key assigned inline
  if grep -qE '(secret_access_key|aws_secret_access_key)[[:space:]]*[:=][[:space:]]*"?[A-Za-z0-9/+=]{40,}' "$f" 2>/dev/null; then
    echo "  SECRET ACCESS KEY       $f"; hits=$((hits+1))
  fi
  # Private key material
  if grep -qE 'BEGIN (RSA|OPENSSH|EC|PGP) PRIVATE KEY' "$f" 2>/dev/null; then
    echo "  PRIVATE KEY             $f"; hits=$((hits+1))
  fi
done

if [ "$hits" -gt 0 ]; then
  echo
  echo "  $hits finding(s). This repo is PUBLIC — move the value into vault or an"
  echo "  env var and reference it. Committing then deleting does NOT remove it."
  exit 1
fi
echo "  secrets: OK"
