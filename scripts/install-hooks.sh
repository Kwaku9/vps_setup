#!/bin/sh
# Install repo hooks. .git/hooks is NOT version-controlled, so a fresh clone has
# no protection until this runs — which is the usual reason such checks quietly
# stop applying. Run once after cloning.
set -eu
R="$(cd "$(dirname "$0")/.." && pwd)"
cat > "$R/.git/hooks/pre-commit" <<'HOOK'
#!/bin/sh
set -e
R=$(git rev-parse --show-toplevel)
"$R/scripts/lint-secrets.sh"
"$R/scripts/lint-pods.sh"
HOOK
chmod +x "$R/.git/hooks/pre-commit"
echo "  pre-commit hook installed: lint-secrets + lint-pods"
