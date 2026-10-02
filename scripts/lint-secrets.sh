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

# Default: only what is being committed, which is what a pre-commit hook wants.
# `--all` scans every tracked file, for an audit. Without that mode the lint
# reports "OK" on a repo with known findings simply because nothing is staged,
# which reads as a pass and is not one.
if [ "${1:-}" = "--all" ]; then
  FILES=$(git ls-files)
else
  FILES=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || git ls-files)
fi
[ -n "$FILES" ] || { echo "  secrets: nothing to scan"; exit 0; }

# Ask GIT which files are encrypted, rather than glob-matching .gitattributes
# ourselves. The old version did the latter, and it was wrong in the one
# direction that matters: in a shell `case` pattern `*` MATCHES `/`, while in
# gitattributes it does NOT. So a rule like `tools/*.py` made this lint skip
# `tools/redaction/redact.py` as "encrypted" when git was leaving it in the
# clear. The lint was blind to exactly the files in the coverage gap, which is
# how a plaintext hostname reached this public repo unnoticed (audited
# 2026-10-01). git check-attr is git's own answer and cannot drift from it.
ENC=$(printf '%s\n' $FILES | git check-attr --stdin filter 2>/dev/null \
        | awk -F': ' '$3 == "git-crypt" { print $1 }')

is_encrypted() {
  # Consume the whole list. grep -q exits on its first match and closes the
  # pipe while printf is still writing, producing spurious Broken pipe errors
  # once the encrypted path list grows past the pipe buffer.
  printf '%s\n' "$ENC" | grep -xF "$1" >/dev/null
}

hits=0
warns=0
for f in $FILES; do
  [ -f "$f" ] || continue
  is_encrypted "$f" && continue
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
  # Tailscale MagicDNS hostname. Unambiguous and zero false positives, and the
  # exact class that leaked: real values belong in all.yml (encrypted) as
  # laptop_tailnet_host / vps_tailnet_host and are referenced as {{ vars }}.
  if grep -qE '\b[a-z0-9-]+\.[a-z0-9-]+\.ts\.net\b' "$f" 2>/dev/null; then
    echo "  TAILNET HOSTNAME        $f"; hits=$((hits+1))
  fi
  # Cloudflare zone / DNS-record id in an API URL. The existing account_id rule
  # above does not see these: they sit in the URL PATH, not an assignment.
  if grep -qE 'api\.cloudflare\.com/client/v4/(zones|accounts)/[0-9a-f]{32}' "$f" 2>/dev/null; then
    echo "  CLOUDFLARE ZONE ID      $f"; hits=$((hits+1))
  fi
  # AWS account id, only in an AWS context so a random 12-digit number is not a
  # finding. WARN, not block: these appear in comments and ARNs all over IaC and
  # an account id alone grants nothing.
  if grep -qE 'arn:aws:[a-z0-9-]*:[a-z0-9-]*:[0-9]{12}:|(aws_)?account_id[[:space:]]*[:=][[:space:]]*"?[0-9]{12}' "$f" 2>/dev/null; then
    echo "  warn: AWS ACCOUNT ID    $f"; warns=$((warns+1))
  fi
done

if [ "$hits" -gt 0 ]; then
  echo
  echo "  $hits finding(s). This repo is PUBLIC — move the value into vault or an"
  echo "  env var and reference it. Committing then deleting does NOT remove it."
  exit 1
fi
[ "$warns" -gt 0 ] && echo "  secrets: OK ($warns warning(s), not blocking)"
[ "$warns" -gt 0 ] || echo "  secrets: OK"
