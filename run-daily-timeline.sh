#!/bin/bash
# run-daily-timeline.sh — Daily orchestrator for timeline.aicortex.cloud
#
# Mirrors the steps in ~/.claude/commands/update-timeline.md so the live
# timeline stays current without manual intervention. Triggered by the
# sync-claude-timeline.timer systemd user timer (04:00 daily).
#
# Each step logs to ~/.claude/timeline-daily.log with a timestamp.
# Failures abort with a numeric exit code per step (1=sync, 2=ingest, etc).
#
# Manual invocation: ~/Projects/VScdeProjects/vps_setup/run-daily-timeline.sh

set -uo pipefail

VPS=root@alpine-vps
REPO=/home/general/Projects/VScdeProjects/vps_setup
JT_DIR=/home/general/Projects/VScdeProjects/journey-tracker
VPS_DATA=/opt/podman-data/journey-tracker
LOG=/home/general/.claude/timeline-daily.log

mkdir -p "$(dirname "$LOG")"

log() { printf '[%s] %s\n' "$(date -Iseconds)" "$*" | tee -a "$LOG"; }
run() { log "$ $*"; "$@" >>"$LOG" 2>&1; }

log "================================================================"
log "Daily timeline pipeline starting"
log "================================================================"

# -------------------------------------------------------------------
# Step 1 — Sync local Claude sessions to VPS staging
# -------------------------------------------------------------------
log "Step 1: sync sessions to VPS"
if ! "$REPO/sync-sessions-to-vps.sh" >>"$LOG" 2>&1; then
    log "FAIL step 1: sync exited $?"
    exit 1
fi

# -------------------------------------------------------------------
# Step 2 — Trigger ingestion on VPS
# (VPS also has its own 03:00 cron — this is idempotent re-run)
# -------------------------------------------------------------------
log "Step 2: ingest on VPS"
if ! ssh "$VPS" /opt/compose/session-ingestion/daily-ingest.sh >>"$LOG" 2>&1; then
    log "FAIL step 2: ingest exited $?"
    exit 2
fi

# -------------------------------------------------------------------
# Step 3a — Ensure Neo4j is running on Fedora
# -------------------------------------------------------------------
log "Step 3a: ensure Neo4j is running"
NEO4J_OK=0
if docker ps --filter name=neo4j-local --filter status=running --format '{{.Names}}' | grep -q neo4j-local; then
    NEO4J_OK=1
    log "Neo4j already running"
else
    log "Neo4j not running, starting"
    (cd "$REPO/local/neo4j-graph" && docker compose up -d) >>"$LOG" 2>&1
    sleep 15
    if docker exec neo4j-local cypher-shell -u neo4j -p sessiongraph2024 "RETURN 1" >>"$LOG" 2>&1; then
        NEO4J_OK=1
    else
        log "WARN: Neo4j unreachable after start — proceeding without graph ETL"
    fi
fi

# -------------------------------------------------------------------
# Step 3b — Classify new sessions on VPS (LLM, costs money, idempotent)
# -------------------------------------------------------------------
log "Step 3b: classify new sessions"
ssh "$VPS" bash <<'REMOTE' >>"$LOG" 2>&1
set -e
export DB_PASSWORD="$(grep DB_PASSWORD /opt/compose/session-ingestion/daily-ingest.sh | cut -d\" -f2)"
export DB_HOST="$(podman inspect postgres --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
export LITELLM_MASTER_KEY="$(podman inspect litellm --format '{{range .Config.Env}}{{println .}}{{end}}' | grep LITELLM_MASTER_KEY | cut -d= -f2)"
python3 /opt/compose/session-ingestion/classify-sessions.py
REMOTE
CLASSIFY_RC=$?
[ $CLASSIFY_RC -ne 0 ] && log "WARN step 3b: classify exited $CLASSIFY_RC (continuing)"

# -------------------------------------------------------------------
# Step 3c — Neo4j ETL via SSH tunnel (skip if Neo4j unavailable)
# -------------------------------------------------------------------
if [ "$NEO4J_OK" = "1" ]; then
    log "Step 3c: Neo4j ETL via SSH tunnel"
    PG_IP=$(ssh "$VPS" 'podman inspect postgres --format "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"')
    if [ -n "$PG_IP" ]; then
        # Kill any stale tunnel on 15432
        pkill -f 'ssh.*15432:.*:5432' 2>/dev/null || true
        ssh -L "15432:$PG_IP:5432" -N "$VPS" &
        TUNNEL_PID=$!
        sleep 3
        (cd "$REPO/local/etl" && PG_PORT=15432 PYTHONIOENCODING=utf-8 python sync_sessions_to_neo4j.py) >>"$LOG" 2>&1 \
            || log "WARN step 3c: ETL failed (continuing without graph data)"
        kill "$TUNNEL_PID" 2>/dev/null || true
    else
        log "WARN step 3c: could not resolve postgres IP, skipping ETL"
    fi
else
    log "Step 3c: skipped (Neo4j unavailable)"
fi

# -------------------------------------------------------------------
# Step 3d — Extract journey dataset
# -------------------------------------------------------------------
log "Step 3d: extract dataset"
PG_IP=$(ssh "$VPS" 'podman inspect postgres --format "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"')
if [ -z "$PG_IP" ]; then
    log "FAIL step 3d: could not resolve postgres IP"
    exit 3
fi
if ! (cd "$JT_DIR" && DB_REMOTE_HOST="$PG_IP" node extract-sessions.js) >>"$LOG" 2>&1; then
    log "FAIL step 3d: extract-sessions.js exited $?"
    exit 3
fi

# -------------------------------------------------------------------
# Sanity check the dataset before deploying (no overwriting live site
# with a broken file).
# -------------------------------------------------------------------
DS="$JT_DIR/journey-dataset.json"
if [ ! -s "$DS" ]; then
    log "FAIL pre-deploy: $DS is empty or missing"
    exit 4
fi
if ! jq empty "$DS" 2>>"$LOG"; then
    log "FAIL pre-deploy: $DS is not valid JSON"
    exit 4
fi
log "Dataset OK: $(stat -c%s "$DS") bytes, $(jq '.sessions | length' "$DS") sessions"

# -------------------------------------------------------------------
# Step 4 — Deploy timeline.html (also as index.html) + dataset
# -------------------------------------------------------------------
log "Step 4: deploy to VPS"
cd "$JT_DIR"
if ! scp timeline.html "$VPS:$VPS_DATA/timeline.html" >>"$LOG" 2>&1; then
    log "FAIL step 4: scp timeline.html failed"
    exit 4
fi
scp timeline.html "$VPS:$VPS_DATA/index.html" >>"$LOG" 2>&1
scp journey-dataset.json "$VPS:$VPS_DATA/journey-dataset.json" >>"$LOG" 2>&1

log "✓ Pipeline complete — https://timeline.aicortex.cloud"
log "================================================================"
exit 0
