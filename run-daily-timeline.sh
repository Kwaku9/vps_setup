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
# Pre-flight — warn (non-fatal) if any deployed file has drifted from its
# canonical repo source. Catches direct edits on /opt/compose/... that a future
# Ansible deploy would silently revert (see the 2026-06-15 ingest-sessions.py
# incident). Best-effort: never blocks the timeline.
# -------------------------------------------------------------------
log "Pre-flight: checking deploy drift (repo vs VPS)"
if ! "$REPO/tools/check-vps-drift.sh" >>"$LOG" 2>&1; then
    log "WARN pre-flight: deploy drift detected — see log above; continuing (non-fatal)"
fi

# -------------------------------------------------------------------
# Step 1 — Sync local Claude sessions to VPS staging
# -------------------------------------------------------------------
log "Step 1: sync sessions to VPS"
# NOTE: capture rc on its own line. Inside `if ! cmd; then`, `$?` is the
# *`if` test's* status (always 0), so the old form reported "exited 0" on
# every failure and hid the real code.
"$REPO/sync-sessions-to-vps.sh" >>"$LOG" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
    log "FAIL step 1: sync exited $rc"
    exit 1
fi

# -------------------------------------------------------------------
# Step 1b — Sync Codex sessions to VPS staging (non-fatal)
# -------------------------------------------------------------------
log "Step 1b: sync Codex sessions to VPS"
if ! "$REPO/sync-codex-sessions-to-vps.sh" >>"$LOG" 2>&1; then
    log "WARN step 1b: Codex sync failed (continuing)"
fi

# -------------------------------------------------------------------
# Step 2 — Trigger ingestion on VPS
# (VPS also has its own 03:00 cron — this is idempotent re-run)
# -------------------------------------------------------------------
log "Step 2: ingest on VPS"
ssh "$VPS" /opt/compose/session-ingestion/daily-ingest.sh >>"$LOG" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
    # daily-ingest.sh redirects almost everything to the VPS's own log, so
    # this log will look empty. The real error is in
    # /var/log/session-ingest.log on $VPS.
    log "FAIL step 2: ingest exited $rc (see $VPS:/var/log/session-ingest.log)"
    exit 2
fi

# -------------------------------------------------------------------
# Step 3a — Ensure Neo4j is running on Fedora
# -------------------------------------------------------------------
log "Step 3a: ensure Neo4j is running"
NEO4J_OK=0
if docker ps --filter name=neo4j-local --filter status=running --format '{{.Names}}' | grep -q neo4j-local; then
    log "Neo4j already running"
else
    log "Neo4j not running, starting"
    (cd "$REPO/local/neo4j-graph" && docker compose up -d) >>"$LOG" 2>&1
    sleep 15
fi

# Authoritative gate: HOST bolt reachability on :17687 — what step 3c's ETL
# actually connects to, NOT an in-container check. The stack remaps bolt to
# host :17687 to coexist with the livekit-agent neo4j on the default :7687,
# so a container that is "healthy"/running internally can still be
# unreachable from the host if the publish/port-forward isn't up. Probe it
# unconditionally (even when the container was already running) so this
# blind spot can't silently pass through to a 3c connection-refused.
probe_bolt() {
    for _try in 1 2 3 4 5 6; do
        if (exec 3<>/dev/tcp/127.0.0.1/17687) 2>/dev/null; then
            return 0
        fi
        sleep 5
    done
    return 1
}

if probe_bolt; then
    NEO4J_OK=1
    log "Neo4j reachable on host :17687"
else
    # Running-but-unreachable is a real, recurring state: the 05:30
    # neo4j-sync.service oneshot used to leave conmon/rootlessport in its own
    # cgroup, and systemd SIGABRTed them on unit teardown — killing the port
    # forwarder while the container itself stayed "Up (healthy)". Self-heal
    # with one forced restart rather than silently skipping the graph ETL.
    log "WARN: Neo4j container up but :17687 unreachable — forcing restart"
    docker stop -t 30 neo4j-local >>"$LOG" 2>&1 || true
    docker start neo4j-local >>"$LOG" 2>&1 || true
    if probe_bolt; then
        NEO4J_OK=1
        log "Neo4j reachable on host :17687 after restart"
    fi
fi
[ "$NEO4J_OK" = "1" ] || log "WARN: Neo4j unreachable on host :17687 — proceeding without graph ETL"

# -------------------------------------------------------------------
# DB credentials — the database is accessed by a dedicated least-
# privilege role (session_ingest), NOT the postgres superuser. The
# single source of truth is the vault-managed daily-ingest.sh on the
# VPS. Source DB_USER + DB_PASSWORD from it once, into the local env,
# so every DB step (3b remote, 3c/3d local) authenticates as the SAME
# user. Without DB_USER, classify-sessions.py / sync_sessions_to_neo4j.py
# / config.js all silently default to "postgres", which the locked-down
# DB rejects.
# -------------------------------------------------------------------
log "Fetching session_ingest DB credentials from VPS vault file"
eval "$(ssh "$VPS" 'grep -E "^export DB_(USER|PASSWORD)=" /opt/compose/session-ingestion/daily-ingest.sh')"
if [ -z "${DB_USER:-}" ] || [ -z "${DB_PASSWORD:-}" ]; then
    log "FAIL: could not source DB_USER/DB_PASSWORD from VPS daily-ingest.sh"
    exit 3
fi
export DB_USER DB_PASSWORD

# -------------------------------------------------------------------
# Step 3b — Classify new sessions on VPS (LLM, costs money, idempotent)
# -------------------------------------------------------------------
log "Step 3b: classify new sessions"
ssh "$VPS" bash <<'REMOTE' >>"$LOG" 2>&1
set -e
export DB_USER="$(grep '^export DB_USER=' /opt/compose/session-ingestion/daily-ingest.sh | cut -d\" -f2)"
export DB_PASSWORD="$(grep '^export DB_PASSWORD=' /opt/compose/session-ingestion/daily-ingest.sh | cut -d\" -f2)"
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
        # Run the ETL from its own venv. The system interpreter is a moving
        # target — Fedora's jump to python3.14 silently orphaned the psycopg2
        # and neo4j installs, and because this step is non-fatal the graph just
        # stopped updating without anything failing loudly. Rebuild the venv
        # whenever its interpreter or deps go missing.
        ETL_PY="$REPO/local/etl/.venv/bin/python"
        if ! "$ETL_PY" -c 'import psycopg2, neo4j, dotenv' 2>/dev/null; then
            log "Step 3c: (re)building ETL venv — deps missing or interpreter stale"
            rm -rf "$REPO/local/etl/.venv"
            if python3 -m venv "$REPO/local/etl/.venv" >>"$LOG" 2>&1 \
               && "$ETL_PY" -m pip install -q -r "$REPO/local/etl/requirements.txt" >>"$LOG" 2>&1; then
                log "Step 3c: ETL venv rebuilt"
            else
                log "WARN step 3c: could not build ETL venv"
            fi
        fi
        # --- Cypher-level readiness -----------------------------------
        # probe_bolt() only proves the rootlessport forwarder accepts a TCP
        # connection. It does NOT prove the database answers, and the ETL's
        # first heavy stage is a 400k+ row write. Ask for an actual query
        # result, through the ETL's own venv and .env so no credential ever
        # reaches a command line or the process table.
        neo4j_answers() {
            (cd "$REPO/local/etl" && "$ETL_PY" - <<'PYPROBE' 2>/dev/null
import os, sys
from dotenv import load_dotenv
from neo4j import GraphDatabase
# Explicit path, NOT bare load_dotenv(): with no argument it calls
# find_dotenv(), which walks the caller's stack frame and raises
# AssertionError when the script arrives on stdin ("python -"). That made
# the probe fail 100% of the time and spuriously restart Neo4j every run.
load_dotenv(".env")
try:
    drv = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:17687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
        connection_timeout=10,
    )
    with drv.session() as s:
        s.run("RETURN 1").consume()
    drv.close()
except Exception:
    sys.exit(1)
PYPROBE
            )
        }

        avail_mb() { awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo; }

        # Why this exists (2026-09-05): the ETL died 15 min in with a bolt
        # read TimeoutError, and 6 min later the kernel OOM-killed the Neo4j
        # JVM. Neo4j was NOT the hog — heap is capped at 1G and its RSS was
        # 1.5G — but rootless podman stamps these containers with
        # oom_score_adj=200 (oom_score 800), which makes Neo4j the preferred
        # victim whenever the host runs short. Setting oom_score_adj lower is
        # not available to us: an unprivileged process cannot lower it, and
        # podman-compose silently ignores the key (verified). So the levers
        # are: don't start a 15-minute run into a starved host, and recover
        # instead of silently skipping the graph for the day.
        ETL_MIN_MB=2048
        ETL_RC=1
        for attempt in 1 2; do
            avail=$(avail_mb)
            if [ "$avail" -lt "$ETL_MIN_MB" ]; then
                log "Step 3c: only ${avail}MB available (want ${ETL_MIN_MB}MB), waiting up to 120s"
                for _w in 1 2 3 4 5 6 7 8 9 10 11 12; do
                    sleep 10
                    avail=$(avail_mb)
                    [ "$avail" -ge "$ETL_MIN_MB" ] && break
                done
                log "Step 3c: proceeding with ${avail}MB available"
            fi

            if ! neo4j_answers; then
                log "WARN step 3c: Neo4j not answering Cypher on :17687 (attempt $attempt)"
                if [ "$attempt" -eq 1 ]; then
                    docker restart neo4j-local >>"$LOG" 2>&1 || true
                    sleep 20
                fi
            fi

            (cd "$REPO/local/etl" && PG_PORT=15432 PG_USER="$DB_USER" PG_PASSWORD="$DB_PASSWORD" PYTHONIOENCODING=utf-8 "$ETL_PY" sync_sessions_to_neo4j.py) >>"$LOG" 2>&1
            ETL_RC=$?
            [ $ETL_RC -eq 0 ] && break

            # Name the real cause in the log instead of leaving a bare
            # TimeoutError traceback that reads like a network fault.
            if [ "$(docker inspect neo4j-local --format '{{.State.OOMKilled}}' 2>/dev/null)" = "true" ]; then
                log "WARN step 3c: Neo4j was OOM-KILLED during attempt $attempt (host memory exhausted, not a network fault)"
            else
                log "WARN step 3c: ETL attempt $attempt exited $ETL_RC"
            fi
            [ "$attempt" -eq 1 ] && log "Step 3c: retrying once after 60s"
            [ "$attempt" -eq 1 ] && sleep 60
        done

        if [ $ETL_RC -eq 0 ]; then
            log "Step 3c: ETL completed OK"
        else
            log "WARN step 3c: ETL failed after 2 attempts (continuing without graph data)"
        fi
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
(cd "$JT_DIR" && DB_REMOTE_HOST="$PG_IP" DB_USER="$DB_USER" DB_PASSWORD="$DB_PASSWORD" node extract-sessions.js) >>"$LOG" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
    log "FAIL step 3d: extract-sessions.js exited $rc"
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

# -------------------------------------------------------------------
# Step 5 — Publish a compact stats.json to the buildfol.io CDN so the
# modern Overview page (TimelineStats.jsx) auto-updates. NON-FATAL: a
# stats hiccup must never fail the timeline deploy above.
# -------------------------------------------------------------------
log "Step 5: publish stats.json to buildfol.io CDN (non-fatal)"
if node "$JT_DIR/emit-stats.cjs" "$DS" "$JT_DIR/stats.json" >>"$LOG" 2>&1; then
    if aws s3 cp "$JT_DIR/stats.json" s3://buildfolio-modern-assets/modern/stats.json \
        --content-type application/json --cache-control "public, max-age=300" >>"$LOG" 2>&1; then
        log "✓ stats.json published to buildfol.io CDN"
    else
        log "WARN step 5: aws s3 cp of stats.json failed (non-fatal)"
    fi
else
    log "WARN step 5: emit-stats.cjs failed (non-fatal)"
fi

log "✓ Pipeline complete — https://timeline.aicortex.cloud"
log "================================================================"
exit 0
