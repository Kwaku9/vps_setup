#!/bin/sh
# Install repo hooks. .git/hooks is NOT version-controlled, so a fresh clone has
# no protection until this runs — which is the usual reason such checks quietly
# stop applying. Run once after cloning.
set -eu
R="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS="$(cd "$R" && git rev-parse --git-path hooks)"
case "$HOOKS" in /*) ;; *) HOOKS="$R/$HOOKS" ;; esac
mkdir -p "$HOOKS"
cat > "$HOOKS/pre-commit" <<'HOOK'
#!/bin/sh
# Installed by scripts/install-hooks.sh — see that file for rationale.
set -e
R=$(git rev-parse --show-toplevel)
"$R/scripts/lint-secrets.sh"
"$R/scripts/lint-pods.sh"
# The hook is shared by every worktree; only checkouts that have the zone tooling run it.
if [ -f "$R/scripts/lint-zones.sh" ]; then
    "$R/scripts/lint-zones.sh"
fi
HOOK
chmod +x "$HOOKS/pre-commit"
echo "  pre-commit hook installed: lint-secrets + lint-pods + lint-zones (where present)"
