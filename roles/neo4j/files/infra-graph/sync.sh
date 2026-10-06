#!/bin/sh
# infra-graph sync: collect live state -> infra.json -> MERGE into neo4j-db.
# Idempotent; safe to run any time (nightly cron, after a deploy, or by hand).
#
#   collect.py exits 0 when every source succeeded, 2 when some failed. A failed
#   source is still loaded-around safely (the loader neither writes nor deletes
#   its slice), but the run is reported as degraded via the exit code and the
#   infra_graph_source_ok metric.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT:-/opt/compose/infra-graph}"
PROM_DIR="${PROM_DIR:-/opt/compose/textfile-collector}"
mkdir -p "$OUT"

rc=0
python3 "$HERE/collect.py" "$OUT" > "$OUT/last-run.json" || rc=$?
if [ ! -s "$OUT/infra.json" ]; then
    echo "infra-graph: collector produced no output (rc=$rc)" >&2
    exit 1
fi

podman exec neo4j-db sh -c 'mkdir -p /var/lib/neo4j/import'
podman cp "$OUT/infra.json" neo4j-db:/var/lib/neo4j/import/infra.json
podman exec neo4j-db sh -c 'chmod 644 /var/lib/neo4j/import/infra.json'
podman exec -i neo4j-db sh -c 'cypher-shell -u neo4j -p "${NEO4J_AUTH#neo4j/}" --format plain' \
    < "$HERE/load-infra.cypher" > "$OUT/last-load.txt"

# Freshness metrics (node-exporter textfile collector). 0644: node-exporter is
# not root, and a 0600 .prom silently drops every series in it.
python3 - "$OUT/infra.json" > "$OUT/infra_graph.prom.tmp" <<'PY'
import json, sys, calendar, time
d = json.load(open(sys.argv[1]))
ts = calendar.timegm(time.strptime(d["run"], "%Y-%m-%dT%H:%M:%SZ"))
print("# HELP infra_graph_last_run_timestamp_seconds When the infra-graph collector last loaded.")
print("# TYPE infra_graph_last_run_timestamp_seconds gauge")
print(f"infra_graph_last_run_timestamp_seconds {ts}")
print("# HELP infra_graph_source_ok 1 if the source was collected (and reconciled) this run.")
print("# TYPE infra_graph_source_ok gauge")
for k, v in d["sources"].items():
    print(f'infra_graph_source_ok{{source="{k}"}} {1 if v["ok"] else 0}')
print("# HELP infra_graph_objects Objects discovered this run.")
print("# TYPE infra_graph_objects gauge")
for k in ("pods", "containers", "jobs", "datastores", "routes", "dashboards", "scripts", "apis", "api_paths", "credentials", "public_endpoints"):
    print(f'infra_graph_objects{{kind="{k}"}} {len(d.get(k, []))}')
creds = d.get("credentials", [])
if creds:
    print("# HELP infra_graph_credentials Vault secrets by problem flag (names only; see INVENTORY.md).")
    print("# TYPE infra_graph_credentials gauge")
    for flag in ("drift", "conflict", "duplicate_in_file", "unreferenced", "empty"):
        print(f'infra_graph_credentials{{flag="{flag}"}} {sum(1 for c in creds if c.get(flag))}')
    print(f'infra_graph_credentials{{flag="reused"}} {sum(1 for c in creds if c.get("reused_as"))}')
    print(f'infra_graph_credentials{{flag="unmanaged"}} {len(d.get("unmanaged_secrets", []))}')
eps = d.get("public_endpoints", [])
if eps:
    print("# HELP infra_graph_public_endpoints Externally reachable endpoints (see INVENTORY.md).")
    print("# TYPE infra_graph_public_endpoints gauge")
    for kind in ("hostname", "port", "worker"):
        print(f'infra_graph_public_endpoints{{kind="{kind}",set="all"}} {sum(1 for e in eps if e["kind"] == kind)}')
        print(f'infra_graph_public_endpoints{{kind="{kind}",set="flagged"}} {sum(1 for e in eps if e["kind"] == kind and e["flags"])}')
    print(f'infra_graph_public_endpoints{{kind="port",set="internet"}} {sum(1 for e in eps if e["kind"] == "port" and "internet" in e["reachable"])}')
PY
chmod 0644 "$OUT/infra_graph.prom.tmp"
mv "$OUT/infra_graph.prom.tmp" "$PROM_DIR/infra_graph.prom"

cat "$OUT/last-run.json"
grep -E 'deleted|db_client_edges' -A3 "$OUT/last-load.txt" || true
echo "infra-graph sync complete (collector rc=$rc)"
exit "$rc"
