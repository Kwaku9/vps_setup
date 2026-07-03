#!/bin/sh
# sync-recall-graph-now.sh — event-driven session-recall + graph freshness.
#
# Fired by the Claude Code SessionEnd hook (and safe to run by hand). Pushes the
# just-ended local sessions all the way through:
#
#   local jsonl  --rsync-->  VPS staging
#                --ingest-->  Postgres sessions.*      (daily-ingest.sh)
#                --MERGE--->  VPS neo4j-db graph        (sync.sh, inline in daily-ingest.sh)
#                --embed--->  recall.chunks (pgvector)  (embed-recall-now.sh, laptop GPU)
#
# Embedding runs on the LOCAL GPU only; vectors are forwarded up to the VPS.
# Every step is idempotent, so overlap with the 04:35 nightly timer or another
# session-end is harmless. A non-blocking flock means a trigger that arrives while
# one is already running just no-ops (the running pass re-scans the whole corpus,
# and the nightly timer is the catch-all safety net).
#
# Self-contained bundle: embed-recall-now.sh + embed_recall_delta.py live next to
# this script (SCRIPT_DIR), so the whole thing runs straight from the git repo.
set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
VPS=root@100.121.252.38                 # alpine-vps over tailnet
REPO=/home/general/Projects/VScdeProjects/vps_setup   # for sync-sessions-to-vps.sh (repo root)
EMBED="$SCRIPT_DIR/embed-recall-now.sh"
LOG=/home/general/.claude/recall-sync.log
LOCK=/tmp/recall-sync.lock
REASON="${1:-manual}"

log() { printf '[%s] %s\n' "$(date -Iseconds)" "$*" >> "$LOG"; }

# Serialize: skip (don't queue) if a sync already holds the lock.
exec 9>"$LOCK"
if ! flock -n 9; then
  log "skip (reason=$REASON): another recall/graph sync holds the lock"
  exit 0
fi

log "==================== event-driven sync start (reason=$REASON) ===================="

# 1. Push local Claude sessions to VPS staging.
if "$REPO/sync-sessions-to-vps.sh" >> "$LOG" 2>&1; then
  log "step 1 ok: sessions rsynced to VPS staging"
else
  log "FAIL step 1: sync-sessions-to-vps.sh rc=$? — aborting"; exit 1
fi

# 2. Ingest staged sessions -> Postgres, AND refresh the VPS neo4j-db graph
#    (daily-ingest.sh runs sessions-graph/sync.sh inline on success).
if ssh -o ConnectTimeout=10 "$VPS" /opt/compose/session-ingestion/daily-ingest.sh >> "$LOG" 2>&1; then
  log "step 2 ok: Postgres ingest + Neo4j graph sync complete"
else
  log "WARN step 2: daily-ingest.sh rc=$? (continuing to embed)"
fi

# 3. Embed the recall delta on the LOCAL GPU -> forwarded to VPS recall.chunks.
if "$EMBED" >> "$LOG" 2>&1; then
  log "step 3 ok: recall.chunks embedded"
else
  log "WARN step 3: embed rc=$?"
fi

log "==================== event-driven sync done (reason=$REASON) ===================="
