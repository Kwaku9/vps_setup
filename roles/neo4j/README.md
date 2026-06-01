# roles/neo4j

Deploys the **Neo4j graph database + Cypher MCP server** as a single Podman pod
(`neo4j-pod`), and loads the infrastructure **service-map graph** into it.

Pod-first by design (future Kubernetes port): both containers share `neo4j-pod`, so the
MCP server reaches the DB over `bolt://localhost:7687` and the unit maps to one K8s Pod.

## Contents

| Container | Image | Purpose | Bind (loopback) |
|---|---|---|---|
| `neo4j-db` | `neo4j:5-community` (APOC) | graph store | `127.0.0.1:7474` (Browser), `127.0.0.1:7687` (Bolt) |
| `neo4j-mcp-server` | `localhost/neo4j-mcp` (`mcp-neo4j-cypher==0.6.0`) | MCP streamable-http | `127.0.0.1:18080` |

Data: `/opt/podman-data/neo4j/{data,logs,plugins}`.

## Secret

Requires `neo4j_password` in `vault.yml`:

```bash
ansible-vault edit vault.yml      # add:  neo4j_password: <strong-password>
```

## The graph

`docs/service-map.cypher` (generated from `docs/SERVICE-MAP.md`) is copied to the host and
loaded with `cypher-shell` after the DB is ready. The script is **idempotent** (MERGE-based),
so it re-runs safely on every deploy. Schema: `Host, Network, Pod, Container, Datastore,
Database, Role, Route, Middleware, External, Risk`.

## Deploy

```bash
# One-time migration from the hand-deployed standalone containers (data is preserved):
podman rm -f neo4j-mcp-server neo4j-db

# Deploy / update:
ansible-playbook site.yml --tags neo4j

# Rebuild the MCP image only:
ansible-playbook site.yml --tags neo4j-build

# Reload the service-map graph only (DB left running):
ansible-playbook site.yml --tags neo4j-load
```

## Connecting Claude to the MCP

The MCP listens on `127.0.0.1:18080` (streamable-http). Register it in the Claude client:

```bash
claude mcp add --transport http neo4j http://127.0.0.1:18080/...   # path per mcp-neo4j-cypher
```

## Toggles (`defaults/main.yml`)

- `neo4j.enabled` — deploy the role at all.
- `neo4j.load_service_map` — load `service-map.cypher` after deploy (default true).
- `neo4j.mcp.build` — (re)build the MCP image.
