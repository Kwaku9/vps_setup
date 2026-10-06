"""knowledge-mcp: question-shaped tools over the unified knowledge graph in neo4j-db.

The graph joins four layers that are refreshed from live sources:
  code    CodeProject / CodeFile / Symbol / Endpoint      (code-graph indexer)
  docs    Doc -HAS_CLAIM-> Claim {verified|contradicted}   (doc audits + freshness)
  infra   Container / Pod / Database / Route / ScheduledJob / McpServer (infra-graph)
  history Session / Artifact -TOUCHES_FILE-> File          (sessions graph)

Raw Cypher over that schema is easy to get subtly wrong (session activity hangs
off Artifact, not Session; dead copies sit next to live ones; pods publish ports
for their members). These tools encode the right traversals once.

Transport: stdio only, via `podman exec -i knowledge-mcp python /app/server.py`.
No port is opened. Every query runs in a READ transaction, which Neo4j refuses
to write in, so the tools cannot modify the graph.
"""
import os

from mcp.server.fastmcp import FastMCP
from neo4j import GraphDatabase

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.environ.get("NEO4J_USERNAME", "neo4j"), os.environ.get("NEO4J_PASSWORD", ""))
DB = os.environ.get("NEO4J_DATABASE", "neo4j")

mcp = FastMCP("knowledge")
_driver = None


def q(cypher, **params):
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(URI, auth=AUTH)
    with _driver.session(database=DB, default_access_mode="READ") as s:
        return s.execute_read(lambda tx: [r.data() for r in tx.run(cypher, **params)])


# How much a project's class should count when ordering search hits. Live,
# deployed code first; dead duplicates last but still findable.
CLASS_WEIGHT = {"own-deployed": 1.0, "own-dev": 0.8, "own-dormant": 0.6, "unclassified": 0.5, "dead": 0.2}


def rank(hit: dict) -> float:
    """Order search hits. `hit` has: score (Lucene relevance, ~0.5–10),
    label (Symbol|Endpoint|Doc|CodeProject|CodeFile), cls (project class),
    exact (True when the node's name equals the query), freshness (docs only).

    Trade-off: pure text relevance surfaces dead duplicates as often as live
    code (they share names), while weighting by class can bury an exact hit in
    a dormant repo. The default multiplies relevance by class weight and gives
    exact name matches and API surface (Endpoints) a boost.
    """
    s = hit["score"] * CLASS_WEIGHT.get(hit.get("cls") or "unclassified", 0.5)
    if hit.get("exact"):
        s *= 2.0
    if hit["label"] == "Endpoint":
        s *= 1.3
    if hit.get("freshness") == "needs-reaudit":
        s *= 0.8
    return s


@mcp.tool()
def search(text: str, kind: str = "", include_dead: bool = False, limit: int = 15) -> list[dict]:
    """Find where something lives in the user's own code and docs: functions,
    classes, HTTP/MCP endpoints, projects, files and markdown docs across every
    indexed repo on the VPS (about 55 projects, 3,600 symbols, 340 endpoints,
    320 docs; re-indexed nightly). Start here for "where is X implemented",
    "which service exposes /api/Y", or "is there a doc or plan about Z".

    Matching is full-text (Lucene) over names, docstrings, paths and headings,
    so use the identifiers or words likely to appear in code ("ingest_sessions",
    "rerank", "Cloudflare tunnel"), not a whole question. Lucene syntax works:
    "exact phrase", prefix*, a OR b.

    Args: text; kind = symbol | endpoint | doc | project | file (optional
    filter); include_dead (default False hides abandoned duplicate copies);
    limit (default 15).

    Returns hits ranked live-code-first: label, name, kind, project, class
    (own-deployed > own-dev > own-dormant > unclassified > dead), location
    (file:line or path), about (docstring or summary), and for docs doc_status
    (verified / contradicted / unverifiable) and freshness. Many repos have
    near-identical copies; trust own-deployed hits over others. Follow up with
    describe(name) for one hit.

    Not for past conversations (use session-recall) or arbitrary graph
    queries (use neo4j-sessions read_neo4j_cypher).
    """
    labels = {"symbol": "Symbol", "endpoint": "Endpoint", "doc": "Doc", "project": "CodeProject", "file": "CodeFile"}
    rows = q("""
        CALL db.index.fulltext.queryNodes('code_search', $text) YIELD node, score
        WITH node, score, [l IN labels(node) WHERE l IN ['Symbol','Endpoint','Doc','CodeProject','CodeFile']][0] AS label
        WHERE $label = '' OR label = $label
        OPTIONAL MATCH (p:CodeProject) WHERE p.key = coalesce(node.project, node.key)
                         OR (label = 'Doc' AND (node)-[:DESCRIBES]->(p))
        OPTIONAL MATCH (node)<-[:DEFINES]-(f:CodeFile)
        OPTIONAL MATCH (node)-[:DEFINED_IN]->(ef:CodeFile)
        WITH node, score, label, p, coalesce(f, ef) AS file
        RETURN label, score, coalesce(node.qname, node.name, node.rel) AS name, node.kind AS kind,
               p.name AS project, p.class AS cls,
               CASE WHEN file IS NOT NULL THEN file.path + ':' + toString(coalesce(node.line, 1))
                    ELSE node.path END AS location,
               coalesce(node.doc, node.summary, node.title) AS about,
               node.audit_status AS doc_status, node.freshness AS freshness,
               toLower(coalesce(node.name, '')) = toLower($text) AS exact
        LIMIT 200""", text=text, label=labels.get(kind.lower(), ""))
    rows = [r | {"cls": r["cls"] or "unclassified"} for r in rows]
    if not include_dead:
        rows = [r for r in rows if r["cls"] != "dead"]
    rows.sort(key=rank, reverse=True)
    out = []
    for r in rows[:limit]:
        r.pop("score"); r.pop("exact")
        out.append({k: v for k, v in r.items() if v not in (None, "")})
    return out


@mcp.tool()
def describe(name: str) -> dict:
    """Everything the graph knows about ONE named thing, resolved in this
    order: code project, container, database, endpoint or MCP tool,
    function/class, MCP server, doc. Use it after search(), or directly when
    you already have the exact name (e.g. "session-recall-mcp", "neo4j-db",
    "vps_setup").

    What comes back depends on the kind:
    - project: components, endpoints, containers it runs as (and their pod),
      databases used, docs about it, and which copies it supersedes.
    - container: code behind it, pod, public routes, databases, MCP servers
      and scheduled jobs inside it, whether it is backed up.
    - database: tables and which containers read or write it, with role.
    - function/endpoint: file:line, handler, callers and callees, where it runs.
    - doc: each claim with status (contradicted first) and the evidence.

    Names must match exactly: a container ("neo4j-db"), a project key
    ("vps_setup"), a database as "<server>/<db>" ("postgres/enterprise") or
    its bare db name, a qualified symbol. On {"error": "nothing named ..."}
    run search() to find the exact name.
    Infra facts reflect last night's sync, not this minute; check live state
    (podman ps, curl) before acting on them.
    """
    hit = q("""
        CALL () {
          MATCH (n:CodeProject) WHERE n.name = $n OR n.key = $n RETURN n, 0 AS pri
          UNION MATCH (n:Container) WHERE n.name = $n RETURN n, 1 AS pri
          UNION MATCH (n:Database) WHERE n.name = $n OR n.db = $n RETURN n, 2 AS pri
          UNION MATCH (n:Endpoint) WHERE n.name = $n OR n.key = $n RETURN n, 3 AS pri
          UNION MATCH (n:Symbol) WHERE n.qname = $n OR n.name = $n OR n.key = $n RETURN n, 4 AS pri
          UNION MATCH (n:McpServer) WHERE n.name = $n RETURN n, 5 AS pri
          UNION MATCH (n:Doc) WHERE n.rel = $n OR n.path = $n OR n.name = $n RETURN n, 6 AS pri
        }
        OPTIONAL MATCH (p:CodeProject {key: n.project})
        RETURN n, labels(n)[0] AS label, coalesce(p.class, n.class) AS cls
        ORDER BY pri, CASE coalesce(p.class, n.class) WHEN 'own-deployed' THEN 0 WHEN 'dead' THEN 9 ELSE 5 END
        LIMIT 1""", n=name)
    if not hit:
        return {"error": f"nothing named {name!r}; try search()"}
    node, label = hit[0]["n"], hit[0]["label"]
    key = node.get("key") or node.get("name")
    res = {"label": label, "class": hit[0]["cls"],
           "props": {k: v for k, v in node.items() if k not in ("seen", "src", "headings", "env_keys", "decorators")}}

    if label == "CodeProject":
        res["components"] = [r["c"] for r in q("MATCH (c:CodeProject)-[:PART_OF]->(:CodeProject {key:$k}) RETURN c.name AS c", k=key)]
        res["endpoints"] = q("""MATCH (:CodeProject {key:$k})-[:EXPOSES]->(e:Endpoint)-[:DEFINED_IN]->(f:CodeFile)
                                RETURN e.kind AS kind, e.name AS name, f.rel + ':' + toString(e.line) AS at
                                ORDER BY kind, name LIMIT 120""", k=key)
        res["runs_as"] = q("""MATCH (:CodeProject {key:$k})-[d:DEPLOYED_AS]->(c:Container)
                              OPTIONAL MATCH (pod:Pod)-[:CONTAINS]->(c)
                              RETURN DISTINCT c.name AS container, c.state AS state, pod.name AS pod""", k=key)
        res["uses_databases"] = q("""MATCH (:CodeProject {key:$k})-[:DEPLOYED_AS]->(c:Container)
                                     OPTIONAL MATCH (pod:Pod)-[:CONTAINS]->(c)
                                     MATCH (x)-[r:READS|WRITES|USES_DATABASE]->(db:Database) WHERE x = c OR x = pod
                                     RETURN DISTINCT db.name AS database, type(r) AS access, r.user AS role""", k=key)
        res["docs"] = q("""MATCH (d:Doc)-[:DESCRIBES]->(:CodeProject {key:$k})
                           RETURN d.rel AS doc, d.audit_status AS status, d.freshness AS freshness,
                                  d.claims_contradicted AS wrong_claims ORDER BY wrong_claims DESC""", k=key)
        res["superseded_by"] = [r["p"] for r in q("MATCH (:CodeProject {key:$k})-[:SUPERSEDED_BY]->(p) RETURN p.key AS p", k=key)]
        res["copies_of_this"] = [r["p"] for r in q("MATCH (p)-[:SUPERSEDED_BY]->(:CodeProject {key:$k}) RETURN p.path AS p", k=key)]
    elif label in ("Symbol", "Endpoint"):
        res["location"] = q("""MATCH (n {key:$k}) OPTIONAL MATCH (n)<-[:DEFINES]-(f1:CodeFile) OPTIONAL MATCH (n)-[:DEFINED_IN]->(f2:CodeFile)
                               WITH n, coalesce(f1, f2) AS f RETURN f.path + ':' + toString(n.line) AS at, f.last_changed AS file_last_changed""", k=key)
        res["handled_by"] = q("MATCH ({key:$k})-[:HANDLED_BY]->(h:Symbol) RETURN h.qname AS handler, h.sig AS sig, h.doc AS doc", k=key)
        res["exposes"] = q("MATCH (e:Endpoint)-[:HANDLED_BY]->({key:$k}) RETURN e.kind AS kind, e.name AS name", k=key)
        res["calls"] = q("MATCH ({key:$k})-[:CALLS]->(t:Symbol) RETURN t.qname AS callee LIMIT 25", k=key)
        res["called_by"] = q("MATCH (s:Symbol)-[:CALLS]->({key:$k}) RETURN s.qname AS caller LIMIT 25", k=key)
        res["runs_as"] = q("""MATCH (p:CodeProject {key:$p})-[:DEPLOYED_AS]->(c:Container)
                              RETURN DISTINCT c.name AS container, c.state AS state""", p=node.get("project"))
    elif label == "Container":
        res["code"] = q("MATCH (p:CodeProject)-[:DEPLOYED_AS]->(:Container {name:$k}) RETURN DISTINCT p.key AS project, p.class AS class", k=key)
        res["pod"] = [r["p"] for r in q("MATCH (p:Pod)-[:CONTAINS]->(:Container {name:$k}) RETURN p.name AS p", k=key)]
        res["routes"] = q("""MATCH (r:Route)-[:ROUTES_TO]->(t) WHERE t.name = $k OR (t:Pod AND (t)-[:CONTAINS]->(:Container {name:$k}))
                             RETURN r.host AS host, r.path AS path, r.middlewares AS middlewares""", k=key)
        res["databases"] = q("""MATCH (c:Container {name:$k}) OPTIONAL MATCH (pod:Pod)-[:CONTAINS]->(c)
                                MATCH (x)-[r:READS|WRITES|USES_DATABASE]->(db:Database) WHERE x = c OR x = pod
                                RETURN DISTINCT db.name AS database, type(r) AS access, r.user AS role""", k=key)
        res["mcp_servers"] = q("MATCH (m:McpServer)-[:RUNS_IN]->(:Container {name:$k}) RETURN m.name AS name, m.scope AS scope, m.status AS status", k=key)
        res["jobs"] = q("MATCH (j:ScheduledJob)-[:RUNS_IN]->(:Container {name:$k}) RETURN j.name AS job, j.frequency AS freq", k=key)
        res["backed_up"] = bool(q("MATCH (:Container {name:$k})-[:BACKED_UP_BY]->() RETURN 1 AS x LIMIT 1", k=key))
    elif label == "Database":
        res["tables"] = q("""MATCH (:Database {name:$k})-[:HAS_TABLE]->(t:Table)
                             RETURN t.schema + '.' + t.table AS table, t.rows AS rows, t.bytes AS bytes ORDER BY bytes DESC LIMIT 25""", k=key)
        res["clients"] = q("""MATCH (x)-[r:READS|WRITES|USES_DATABASE]->(:Database {name:$k})
                              RETURN labels(x)[0] + ':' + x.name AS client, type(r) AS access, r.user AS role""", k=key)
        res["dashboards"] = q("""MATCH (g:Dashboard)-[:QUERIES]->(:Datasource)-[:READS]->(:Database {name:$k})
                                 RETURN g.title AS dashboard""", k=key)
    elif label == "Doc":
        res["claims"] = q("""MATCH ({key:$k})-[:HAS_CLAIM]->(c:Claim)
                             RETURN c.status AS status, c.text AS claim, c.evidence AS evidence
                             ORDER BY CASE c.status WHEN 'contradicted' THEN 0 WHEN 'unverifiable' THEN 1 ELSE 2 END""", k=key)
    return res


@mcp.tool()
def impact(name: str) -> dict:
    """Blast radius: what breaks if this container, pod or database stops,
    is restarted or is changed. Call it BEFORE any restart, upgrade, prune,
    migration or config change on the VPS, and when diagnosing an outage to
    see what else is affected.

    Args: name = exact container, pod or database name. Databases are named
    "<server>/<db>": e.g. "postgres" (container), "neo4j-pod" (pod),
    "postgres/enterprise" (database).

    Returns: depends_on_it (containers/pods that depend on, read or write it,
    including through the database server it hosts), routes (public host and
    path served by it), mcp_servers, dashboards that query it, scheduled jobs
    that run in it, and the code projects deployed as it.

    Empty lists mean "no edge recorded", not "proven safe": the map is
    rebuilt nightly from live state and can miss runtime-only dependencies.
    """
    return {
        "depends_on_it": q("""
            MATCH (t) WHERE (t:Container OR t:Pod OR t:Database) AND t.name = $n
            CALL (t) {
              MATCH (x)-[r:DEPENDS_ON|READS|WRITES|USES_DATABASE]->(t) RETURN x, type(r) AS how
              UNION MATCH (x)-[r:DEPENDS_ON|READS|WRITES|USES_DATABASE]->(:Database)<-[:HAS_DATABASE]-(:Datastore)-[:RUNS_IN]->(t) RETURN x, type(r) AS how }
            RETURN DISTINCT labels(x)[0] + ':' + x.name AS dependent, how""", n=name),
        "routes": q("""MATCH (r:Route)-[:ROUTES_TO]->(t) WHERE t.name = $n OR (t:Pod AND (t)-[:CONTAINS]->(:Container {name:$n}))
                       RETURN r.host AS host, r.path AS path""", n=name),
        "mcp_servers": q("""MATCH (m:McpServer)-[:RUNS_IN]->(t) WHERE t.name = $n OR (t:Pod AND (t)-[:CONTAINS]->(:Container {name:$n}))
                            RETURN m.name AS server, m.scope AS scope""", n=name),
        "dashboards": q("""MATCH (g:Dashboard)-[:QUERIES]->(:Datasource)-[:READS]->(x)
                           WHERE x.name = $n OR (x:Database AND (x)<-[:HAS_DATABASE]-(:Datastore {name:$n}))
                              OR (x:Datastore AND x.name = $n)
                           RETURN DISTINCT g.title AS dashboard""", n=name),
        "jobs": q("MATCH (j:ScheduledJob)-[:RUNS_IN]->(t {name:$n}) RETURN j.name AS job, j.frequency AS freq", n=name),
        "code": q("""MATCH (p:CodeProject)-[:DEPLOYED_AS]->(c:Container) WHERE c.name = $n OR p.name = $n
                     RETURN DISTINCT p.key AS project, c.name AS container""", n=name),
    }


@mcp.tool()
def stale_docs(project: str = "", limit: int = 30) -> list[dict]:
    """Docs, READMEs, plans and memory notes that are known to be wrong or
    changed since they were checked, worst first. Every doc's factual claims
    are audited against the live code and infra; this returns docs with
    contradicted claims, each with the claim and what is actually true, plus
    docs edited after their audit (freshness = needs-reaudit).

    Use it before trusting a doc to plan work, when a doc and reality
    disagree, or to find documentation to fix. Args: project (optional
    CodeProject name or key, e.g. "vps_setup"); limit (default 30).

    Returns [{doc, project, status, freshness, contradicted, verified,
    wrong: [{claim, actually}]}]. A doc absent from this list is not proven
    correct; it may just be unaudited or unverifiable.
    """
    return q("""
        MATCH (d:Doc) WHERE (d.claims_contradicted > 0 OR d.freshness = 'needs-reaudit')
        OPTIONAL MATCH (d)-[:DESCRIBES]->(p:CodeProject)
        WITH d, p WHERE $p = '' OR p.name = $p OR p.key = $p
        OPTIONAL MATCH (d)-[:HAS_CLAIM]->(c:Claim {status:'contradicted'})
        WITH d, p, collect({claim: c.text, actually: c.evidence})[..8] AS wrong
        RETURN coalesce(d.path, d.rel) AS doc, p.name AS project, d.audit_status AS status,
               d.freshness AS freshness, d.claims_contradicted AS contradicted,
               d.claims_verified AS verified, wrong
        ORDER BY contradicted DESC LIMIT $lim""", p=project, lim=limit)


@mcp.tool()
def history(path: str, limit: int = 20) -> list[dict]:
    """Which past AI sessions edited a file, newest first, to answer "who
    changed this, when, and why". Follow up with session-recall
    get_session(session) to read the reasoning behind the change.

    Args: path = repo-relative path, absolute path, or a trailing fragment
    such as "roles/neo4j/defaults/main.yml" (a bare file name like
    "server.py" matches every file with that name, so prefer a longer
    suffix); limit (default 20).

    Returns [{file, session, title, started, edits}] where edits counts the
    create/modify/delete operations in that session.

    Only covers files inside indexed repos. For any other path, use
    neo4j-sessions: (:Session)-[:HAS_ARTIFACT]->(:Artifact)-[:TOUCHES_FILE]->
    (:File) with f.path ENDS WITH $path.
    """
    return q("""
        MATCH (cf:CodeFile) WHERE cf.rel ENDS WITH $p OR cf.path = $p
        MATCH (cf)-[:SAME_AS]->(f:File)<-[:TOUCHES_FILE]-(a:Artifact)
        OPTIONAL MATCH (s:Session)-[:HAS_ARTIFACT]->(a)
        WITH cf, s, count(a) AS edits
        RETURN cf.path AS file, s.uuid AS session, s.title AS title,
               toString(s.started_at) AS started, edits
        ORDER BY started DESC LIMIT $lim""", p=path, lim=limit)


if __name__ == "__main__":
    mcp.run()
