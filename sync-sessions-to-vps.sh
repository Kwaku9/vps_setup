#!/bin/bash
# Sync local Claude Code sessions to VPS for ingestion.
#
# Walks ~/.claude/projects/<project>/ and rsyncs both primary session files
# (*.jsonl) and nested subagent transcripts (<session-uuid>/subagents/*.jsonl)
# to the VPS staging area. The ingestion script consumes both.
#
# Usage: ./sync-sessions-to-vps.sh [--ingest]
#   --ingest: Also trigger ingestion after syncing

set -uo pipefail

VPS_HOST="root@alpine-vps"
VPS_STAGING="/opt/compose/session-ingestion/staging/local"
LOCAL_PROJECTS_DIR="$HOME/.claude/projects"

echo "============================================================"
echo "Claude Code Session Sync → VPS"
echo "============================================================"
echo "Source: $LOCAL_PROJECTS_DIR"
echo "Target: $VPS_HOST:$VPS_STAGING"
echo ""

if [ ! -d "$LOCAL_PROJECTS_DIR" ]; then
    echo "ERROR: Local projects directory not found: $LOCAL_PROJECTS_DIR"
    exit 1
fi

PROJECT_COUNT=0
SESSION_COUNT=0
FAIL_COUNT=0

for project_dir in "$LOCAL_PROJECTS_DIR"/*/; do
    project_name=$(basename "$project_dir")
    [ ! -d "$project_dir" ] && continue

    # Count ALL .jsonl files in the tree (primary + subagents)
    jsonl_count=$(find "$project_dir" -name "*.jsonl" 2>/dev/null | wc -l)
    [ "$jsonl_count" -eq 0 ] && continue

    echo "Syncing project: $project_name ($jsonl_count session files)"

    # rsync the project tree, filtering to directories + .jsonl files only.
    # -a preserves perms/times, creates remote dirs automatically.
    # Errors surface to stdout instead of being swallowed.
    if rsync -a \
        --include='*/' \
        --include='*.jsonl' \
        --exclude='*' \
        "$project_dir" "$VPS_HOST:$VPS_STAGING/$project_name/"; then
        PROJECT_COUNT=$((PROJECT_COUNT + 1))
        SESSION_COUNT=$((SESSION_COUNT + jsonl_count))
    else
        echo "  ⚠ rsync failed for $project_name (exit $?)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

echo ""
echo "============================================================"
echo "Sync complete: $PROJECT_COUNT projects, $SESSION_COUNT session files"
if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "WARNING: $FAIL_COUNT project(s) failed to sync — see errors above"
fi
echo "============================================================"

if [ "${1:-}" = "--ingest" ]; then
    echo ""
    echo "Triggering ingestion on VPS..."
    ssh "$VPS_HOST" "/opt/compose/session-ingestion/daily-ingest.sh"
    echo "Ingestion complete."
fi

exit $FAIL_COUNT
