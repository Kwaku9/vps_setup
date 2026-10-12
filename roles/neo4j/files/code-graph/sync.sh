#!/bin/sh
# code-graph sync: index code roots (incremental) -> MERGE into neo4j-db ->
# fold in the doc audits -> export freshness metrics.
#
#   sync.sh                 every root in projects.yml (nightly cron)
#   sync.sh vps_setup ...   only these roots (git post-commit/post-merge hooks)
#
# Idempotent. A root that fails to index keeps its previous graph slice.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
BASE="${BASE:-/opt/compose/code-graph}"
PROM_DIR="${PROM_DIR:-/opt/compose/textfile-collector}"
OUT="$BASE/out"; CACHE="$BASE/cache"; AUDIT="$BASE/audit"
mkdir -p "$OUT" "$CACHE" "$AUDIT"
# One writer at a time: the nightly run and hook-triggered runs must not interleave.
exec 9>"$BASE/.lock"
flock 9

cypher() { podman exec -i neo4j-db sh -c 'cypher-shell -u neo4j -p "${NEO4J_AUTH#neo4j/}" --format plain "$@"' sh "$@"; }

ROOT_ARGS=""
for r in "$@"; do ROOT_ARGS="$ROOT_ARGS --root $r"; done
rc=0
# shellcheck disable=SC2086
python3 "$HERE/index.py" --out "$OUT" --cache "$CACHE" $ROOT_ARGS > "$BASE/last-index.json" || rc=$?

podman exec neo4j-db sh -c 'mkdir -p /var/lib/neo4j/import'
load_root() {
    f="$1"; b="$(basename "$f")"
    podman cp "$f" "neo4j-db:/var/lib/neo4j/import/$b"
    podman exec neo4j-db chmod 644 "/var/lib/neo4j/import/$b"
    cypher -P "f => \"$b\"" < "$HERE/load-code.cypher" >> "$BASE/last-load.txt"
}
: > "$BASE/last-load.txt"
if [ $# -gt 0 ]; then
    for r in "$@"; do [ -f "$OUT/code-$r.json" ] && load_root "$OUT/code-$r.json"; done
else
    for f in "$OUT"/code-*.json; do
        case "$f" in */code-audit.json) continue ;; esac
        load_root "$f"
    done
fi

# Doc audits are folded in after the code so Doc nodes exist to attach to.
python3 "$HERE/load_audit.py" "$AUDIT" "$OUT" "$OUT/code-audit.json" > "$BASE/last-audit.json"
podman cp "$OUT/code-audit.json" neo4j-db:/var/lib/neo4j/import/code-audit.json
podman exec neo4j-db chmod 644 /var/lib/neo4j/import/code-audit.json
cypher < "$HERE/load-audit.cypher" >> "$BASE/last-load.txt"

# Freshness metrics (0644: node-exporter is not root).
{
  echo "# HELP code_graph_last_run_timestamp_seconds When the code graph last loaded."
  echo "# TYPE code_graph_last_run_timestamp_seconds gauge"
  echo "code_graph_last_run_timestamp_seconds $(date +%s)"
  echo "# HELP code_graph_docs Docs by audit status and freshness."
  echo "# TYPE code_graph_docs gauge"
  cypher "MATCH (d:Doc) RETURN coalesce(d.audit_status,'unaudited') AS s, coalesce(d.freshness,'unaudited') AS f, count(*) AS n" \
    | tail -n +2 | tr -d '"' | awk -F', ' '{printf "code_graph_docs{status=\"%s\",freshness=\"%s\"} %s\n",$1,$2,$3}'
  echo "# HELP code_graph_nodes Nodes per code-graph label."
  echo "# TYPE code_graph_nodes gauge"
  cypher "UNWIND ['CodeProject','CodeFile','Symbol','Endpoint','Doc','Claim'] AS l CALL { WITH l MATCH (n) WHERE l IN labels(n) RETURN count(n) AS n } RETURN l, n" \
    | tail -n +2 | tr -d '"' | awk -F', ' '{printf "code_graph_nodes{label=\"%s\"} %s\n",$1,$2}'
} > "$BASE/code_graph.prom.tmp"
chmod 0644 "$BASE/code_graph.prom.tmp"
mv "$BASE/code_graph.prom.tmp" "$PROM_DIR/code_graph.prom"

cat "$BASE/last-audit.json"
echo "code-graph sync complete (index rc=$rc)"
exit "$rc"
