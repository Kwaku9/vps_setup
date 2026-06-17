#!/bin/bash
# check-vps-drift.sh — detect drift between canonical repo sources and the files
# actually deployed on the VPS.
#
# WHY THIS EXISTS
#   Ansible deploys these files by COPYING them verbatim from the repo. If
#   someone edits the deployed copy under /opt/compose/... directly (instead of
#   editing the repo source and re-running the play), two bad things follow:
#     1. the repo's "source of truth" is silently a lie, and
#     2. the next deploy of that role REVERTS the live change without warning.
#   This is exactly what happened on 2026-06-15: ingest-sessions.py was refactored
#   directly on the VPS and never committed, so canonical lagged the live box and
#   a deploy would have reintroduced a fixed bug. This check surfaces that drift.
#
# WHAT IT CHECKS
#   Only files Ansible copies VERBATIM (sha256 must match). git-crypt files are
#   decrypted in the working tree, so they compare correctly. TEMPLATED files
#   (e.g. daily-ingest.sh, rendered from .j2 with vault vars) are intentionally
#   NOT checked — they legitimately differ from any repo file.
#
# USAGE
#   tools/check-vps-drift.sh            # VPS defaults to root@alpine-vps
#   VPS=root@host tools/check-vps-drift.sh
# EXIT: 0 = in sync, 1 = drift or a missing file on either side.
set -uo pipefail

VPS="${VPS:-root@alpine-vps}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# repo-relative source | absolute path on the VPS  (Ansible 'copy' file tasks)
FILE_PAIRS="
tools/ingest-sessions.py|/opt/compose/session-ingestion/ingest-sessions.py
tools/classify-sessions.py|/opt/compose/session-ingestion/classify-sessions.py
tools/ingest-git-history.py|/opt/compose/session-ingestion/ingest-git-history.py
tools/git-schema.sql|/opt/compose/session-ingestion/git-schema.sql
"
# directory synced verbatim (Ansible 'copy' of a dir): repo dir -> vps dir
GRAPH_SRC="roles/neo4j/files/sessions-graph"
GRAPH_DST="/opt/compose/sessions-graph"

drift=0
sha_local() { sha256sum "$1" 2>/dev/null | cut -d' ' -f1; }

check_pair() {
    local rel="$1" remote="$2" l r
    l="$(sha_local "$REPO/$rel")"
    # -n: redirect ssh stdin from /dev/null so it can't swallow a caller's
    # `while read` loop input (this function runs inside one).
    r="$(ssh -n "$VPS" "sha256sum '$remote' 2>/dev/null" | cut -d' ' -f1)"
    if   [ -z "$l" ]; then printf 'MISS-REPO  %s\n' "$rel";    drift=1
    elif [ -z "$r" ]; then printf 'MISS-VPS   %s\n' "$remote"; drift=1
    elif [ "$l" = "$r" ]; then printf 'ok         %s\n' "$rel"
    else printf 'DRIFT      %s\n             repo=%s\n             vps =%s\n' "$rel" "$l" "$r"; drift=1
    fi
}

echo "== deploy drift: repo ($REPO) vs VPS ($VPS) =="

while IFS='|' read -r rel remote; do
    [ -z "$rel" ] && continue
    check_pair "$rel" "$remote"
done <<< "$FILE_PAIRS"

# sessions-graph directory, file by file
if [ -d "$REPO/$GRAPH_SRC" ]; then
    for f in "$REPO/$GRAPH_SRC"/*; do
        [ -f "$f" ] || continue
        base="$(basename "$f")"
        check_pair "$GRAPH_SRC/$base" "$GRAPH_DST/$base"
    done
fi

if [ "$drift" -ne 0 ]; then
    echo "DRIFT DETECTED — deployed file(s) differ from canonical repo sources."
    echo "Reconcile EITHER by committing the VPS change into the repo source,"
    echo "OR by re-running the owning Ansible role to overwrite the VPS copy."
    exit 1
fi
echo "OK — all deployed files match canonical repo sources."
exit 0
