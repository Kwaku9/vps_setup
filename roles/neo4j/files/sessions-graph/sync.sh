#!/bin/sh
# Idempotent sessions-graph sync: export Postgres -> CSV, stage into Neo4j's
# in-container import dir, run the idempotent LOAD CSV MERGE loader.
# Safe to re-run any time (cron or manual); never duplicates nodes/relationships.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
STAGE="${STAGE:-/opt/compose/sessions-graph/csv}"
mkdir -p "$STAGE"

# 1. export (sanitised CSVs, natural keys resolved)
"$HERE/export-full.sh" "$STAGE"

# 2. stage into the neo4j container's import dir (no host bind-mount required)
podman exec neo4j-db sh -c 'mkdir -p /var/lib/neo4j/import'
for f in "$STAGE"/sg_*.csv; do podman cp "$f" neo4j-db:/var/lib/neo4j/import/; done
podman exec neo4j-db sh -c 'chmod 644 /var/lib/neo4j/import/sg_*.csv'

# 3. load (idempotent UPSERT). Password read from the container's own env.
podman exec -i neo4j-db sh -c 'cypher-shell -u neo4j -p "${NEO4J_AUTH#neo4j/}" --format plain' < "$HERE/load-full.cypher"

# 4. report
podman exec neo4j-db sh -c 'cypher-shell -u neo4j -p "${NEO4J_AUTH#neo4j/}" --format plain \
  "MATCH (n) WHERE any(l IN labels(n) WHERE l IN [\"Session\",\"Message\",\"ToolCall\",\"Subagent\",\"Artifact\",\"Project\",\"Commit\"]) \
   RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label"'
echo "sessions-graph sync complete"
