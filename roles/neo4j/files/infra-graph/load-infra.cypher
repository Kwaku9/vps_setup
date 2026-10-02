// =============================================================================
// infra-graph loader — MERGE collector output (infra.json) into neo4j-db.
//
// Input: /var/lib/neo4j/import/infra.json, written by collect.py and copied in
// by sync.sh. Every node and relationship written here carries:
//   src   which collector source asserted it (podman|db|cron|traefik|grafana|backup)
//   seen  the run timestamp
// The final block deletes what a SUCCESSFUL source did not see this run. A
// source that failed (d.sources.<src>.ok = false) keeps its slice untouched.
//
// Owned labels (deleted when unseen): Host Network Pod Container Datastore
// Database Table ScheduledJob Route Middleware Datasource Dashboard McpServer.
// Not owned, never touched: Risk, External, Role and the whole sessions graph.
// =============================================================================

// ---------- constraints ----------
DROP CONSTRAINT route_host IF EXISTS;
CREATE CONSTRAINT route_key      IF NOT EXISTS FOR (n:Route)        REQUIRE n.key  IS UNIQUE;
CREATE CONSTRAINT job_name       IF NOT EXISTS FOR (n:ScheduledJob) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT table_name     IF NOT EXISTS FOR (n:Table)        REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT dashboard_uid  IF NOT EXISTS FOR (n:Dashboard)    REQUIRE n.uid  IS UNIQUE;
CREATE CONSTRAINT datasource_uid IF NOT EXISTS FOR (n:Datasource)   REQUIRE n.uid  IS UNIQUE;
CREATE CONSTRAINT host_name      IF NOT EXISTS FOR (n:Host)         REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT network_name   IF NOT EXISTS FOR (n:Network)      REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT pod_name       IF NOT EXISTS FOR (n:Pod)          REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT container_name IF NOT EXISTS FOR (n:Container)    REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT datastore_name IF NOT EXISTS FOR (n:Datastore)    REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT database_name  IF NOT EXISTS FOR (n:Database)     REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT mw_name        IF NOT EXISTS FOR (n:Middleware)   REQUIRE n.name IS UNIQUE;

// ---------- podman: host, networks, pods, containers ----------
CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.podman.ok
MERGE (h:Host {name: d.host}) SET h.src = 'podman', h.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.podman.ok
UNWIND d.networks AS n
MERGE (x:Network {name: n.name})
SET x.cidr = n.subnet, x.driver = n.driver, x.src = 'podman', x.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.podman.ok
UNWIND d.pods AS p
MATCH (h:Host {name: d.host})
MERGE (x:Pod {name: p.name})
SET x.status = p.status, x.src = 'podman', x.seen = datetime(d.run)
MERGE (x)-[r:RUNS_ON]->(h) SET r.src = 'podman', r.seen = datetime(d.run)
WITH d, p, x
UNWIND keys(p.networks) AS net
MATCH (n:Network {name: net})
MERGE (x)-[r:ON_NETWORK]->(n) SET r.ip = p.networks[net], r.src = 'podman', r.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.podman.ok
UNWIND d.containers AS c
MATCH (h:Host {name: d.host})
MERGE (x:Container {name: c.name})
SET x.image = c.image, x.state = c.state, x.oom_killed = c.oom_killed, x.started = c.started,
    x.restart_policy = c.restart_policy, x.memory_limit = c.memory_limit, x.ports = c.ports,
    x.env_keys = c.env_keys, x.pod = c.pod, x.standalone = (c.pod = ''),
    x.mounts = [m IN c.mounts | coalesce(m.source, m.name, '?') + ':' + coalesce(m.dest, '?')],
    x.src = 'podman', x.seen = datetime(d.run)
MERGE (x)-[r:RUNS_ON]->(h) SET r.src = 'podman', r.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.podman.ok
UNWIND d.containers AS c
WITH d, c WHERE c.pod <> ''
MATCH (x:Container {name: c.name}), (p:Pod {name: c.pod})
MERGE (p)-[r:CONTAINS]->(x) SET r.src = 'podman', r.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.podman.ok
UNWIND d.containers AS c
WITH d, c WHERE c.pod = ''
UNWIND keys(c.networks) AS net
MATCH (x:Container {name: c.name}), (n:Network {name: net})
MERGE (x)-[r:ON_NETWORK]->(n) SET r.ip = c.networks[net], r.src = 'podman', r.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.podman.ok AND d.sources.db.ok
UNWIND d.containers AS c
UNWIND c.depends AS dep
MATCH (a:Container {name: c.name}), (b:Container {name: dep.to})
MERGE (a)-[r:DEPENDS_ON]->(b)
SET r.via = dep.via, r.db = dep.db, r.src = 'podman', r.seen = datetime(d.run);

// ---------- db: datastores, databases, tables, live clients ----------
CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.db.ok
UNWIND d.datastores AS s
MERGE (x:Datastore {name: s.name})
SET x.engine = s.engine, x.bytes = s.bytes, x.state = s.state, x.roles = s.roles, x.mtime = s.mtime,
    x.src = 'db', x.seen = datetime(d.run)
WITH d, s, x WHERE s.container IS NOT NULL
MATCH (c:Container {name: s.container})
MERGE (x)-[r:RUNS_IN]->(c) SET r.src = 'db', r.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.db.ok
UNWIND d.datastores AS s
UNWIND s.databases AS db
MATCH (x:Datastore {name: s.name})
MERGE (y:Database {name: db.name})
SET y.db = db.db, y.engine = s.engine, y.bytes = db.bytes, y.nodes = db.nodes, y.keys = db.keys,
    y.tables = size(db.tables), y.src = 'db', y.seen = datetime(d.run)
MERGE (x)-[r:HAS_DATABASE]->(y) SET r.src = 'db', r.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.db.ok
UNWIND d.datastores AS s
UNWIND s.databases AS db
UNWIND db.tables AS t
MATCH (y:Database {name: db.name})
MERGE (z:Table {name: t.name})
SET z.schema = t.schema, z.table = t.table, z.rows = t.rows, z.bytes = t.bytes,
    z.src = 'db', z.seen = datetime(d.run)
MERGE (y)-[r:HAS_TABLE]->(z) SET r.src = 'db', r.seen = datetime(d.run);

// Observed clients (pg_stat_activity). READS vs WRITES comes from the role's
// actual write capability in that database, not from the client's intent.
CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.db.ok
UNWIND d.datastores AS s
UNWIND s.databases AS db
UNWIND db.clients AS cl
MATCH (y:Database {name: db.name})
OPTIONAL MATCH (c:Container {name: cl.who})
OPTIONAL MATCH (p:Pod {name: cl.who})
WITH d, y, cl, coalesce(c, p) AS a WHERE a IS NOT NULL
CALL apoc.merge.relationship(a, CASE WHEN cl.writes THEN 'WRITES' ELSE 'READS' END,
                             {user: cl.user}, {}, y, {}) YIELD rel
SET rel.conns = cl.conns, rel.observed = true, rel.src = 'db', rel.seen = datetime(d.run)
RETURN count(rel) AS db_client_edges;

// Declared clients (connection settings in container env), when a database is named.
CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.podman.ok AND d.sources.db.ok
UNWIND d.containers AS c
UNWIND c.depends AS dep
WITH d, c, dep WHERE dep.db <> ''
MATCH (a:Container {name: c.name}), (y:Database {name: dep.to + '/' + dep.db})
MERGE (a)-[r:USES_DATABASE]->(y) SET r.via = dep.via, r.src = 'db', r.seen = datetime(d.run);

// ---------- cron: scheduled jobs ----------
CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.cron.ok
UNWIND d.jobs AS j
MERGE (x:ScheduledJob {name: j.name})
SET x.schedule = j.schedule, x.frequency = j.frequency, x.command = j.command,
    x.ansible_managed = j.managed, x.log = j.log, x.src = 'cron', x.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.cron.ok
UNWIND d.jobs AS j
WITH d, j WHERE size(j.runs_in) = 0
MATCH (x:ScheduledJob {name: j.name}), (h:Host {name: d.host})
MERGE (x)-[r:RUNS_IN]->(h) SET r.src = 'cron', r.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.cron.ok
UNWIND d.jobs AS j
UNWIND j.runs_in AS cn
MATCH (x:ScheduledJob {name: j.name}), (c:Container {name: cn})
MERGE (x)-[r:RUNS_IN]->(c) SET r.src = 'cron', r.seen = datetime(d.run);

// ---------- traefik: routes and middlewares ----------
CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.traefik.ok
UNWIND d.middlewares AS m
MERGE (x:Middleware {name: m}) SET x.src = 'traefik', x.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.traefik.ok
UNWIND d.routes AS rt
MERGE (x:Route {key: rt.key})
SET x.host = rt.host, x.path = rt.path, x.router = rt.router, x.file = rt.file,
    x.service = rt.service, x.middlewares = rt.middlewares,
    x.src = 'traefik', x.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.traefik.ok
UNWIND d.routes AS rt
UNWIND rt.backends AS b
MATCH (x:Route {key: rt.key})
OPTIONAL MATCH (c:Container {name: b.to})
OPTIONAL MATCH (p:Pod {name: b.pod})
WITH d, x, b, coalesce(c, p) AS t WHERE t IS NOT NULL
MERGE (x)-[r:ROUTES_TO]->(t) SET r.url = b.url, r.src = 'traefik', r.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.traefik.ok
UNWIND d.routes AS rt
UNWIND range(0, size(rt.middlewares) - 1) AS i
MATCH (x:Route {key: rt.key}), (m:Middleware {name: rt.middlewares[i]})
MERGE (x)-[r:USES_MIDDLEWARE]->(m) SET r.order = i, r.src = 'traefik', r.seen = datetime(d.run);

// ---------- grafana: datasources and dashboards ----------
CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.grafana.ok
UNWIND d.datasources AS s
MERGE (x:Datasource {uid: s.uid})
SET x.name = s.name, x.type = s.type, x.db = s.db, x.target = s.target,
    x.src = 'grafana', x.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.grafana.ok
UNWIND d.datasources AS s
WITH d, s WHERE s.target IS NOT NULL
MATCH (x:Datasource {uid: s.uid})
OPTIONAL MATCH (db:Database {name: s.target + '/' + s.db})
OPTIONAL MATCH (st:Datastore)-[:RUNS_IN]->(:Container {name: s.target})
WITH d, x, coalesce(db, st) AS t WHERE t IS NOT NULL
MERGE (x)-[r:READS]->(t) SET r.src = 'grafana', r.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.grafana.ok
UNWIND d.dashboards AS g
MERGE (x:Dashboard {uid: g.uid})
SET x.title = g.title, x.folder = g.folder, x.src = 'grafana', x.seen = datetime(d.run)
WITH d, g, x
UNWIND g.datasources AS u
MATCH (s:Datasource {uid: u})
MERGE (x)-[r:QUERIES]->(s) SET r.src = 'grafana', r.seen = datetime(d.run);

// ---------- backup coverage ----------
CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.backup.ok AND d.sources.cron.ok
MATCH (j:ScheduledJob {name: d.backup.job})
UNWIND d.backup.covered AS cv
MATCH (c:Container {name: cv.container})
MERGE (c)-[r:BACKED_UP_BY]->(j) SET r.paths = cv.paths, r.src = 'backup', r.seen = datetime(d.run);

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.backup.ok AND d.sources.cron.ok AND d.sources.db.ok
MATCH (j:ScheduledJob {name: d.backup.job})
UNWIND d.datastores AS s
WITH d, j, s WHERE s.engine = 'sqlite' AND any(x IN d.backup.dirs WHERE s.name STARTS WITH x + '/')
MATCH (st:Datastore {name: s.name})
MERGE (st)-[r:BACKED_UP_BY]->(j) SET r.src = 'backup', r.seen = datetime(d.run);

// ---------- mcp: configured MCP servers (Claude Code user/local/plugin/claude.ai) ----------
CREATE CONSTRAINT mcp_key IF NOT EXISTS FOR (n:McpServer) REQUIRE n.key IS UNIQUE;

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d WHERE d.sources.mcp.ok
UNWIND d.mcp_servers AS m
MERGE (x:McpServer {key: m.key})
SET x.name = m.name, x.scope = m.scope, x.where = m.where, x.transport = m.transport,
    x.command = m.command, x.args = m.args, x.url = m.url, x.env_keys = m.env_keys,
    x.header_keys = m.header_keys, x.status = m.status, x.src = 'mcp', x.seen = datetime(d.run)
WITH d, m, x
OPTIONAL MATCH (c:Container {name: m.container})
OPTIONAL MATCH (p:Pod {name: m.pod})
WITH d, x, coalesce(c, p) AS t WHERE t IS NOT NULL
MERGE (x)-[r:RUNS_IN]->(t) SET r.src = 'mcp', r.seen = datetime(d.run);

// ---------- reconcile: delete what successful sources no longer see ----------
CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d, datetime(d.run) AS run,
     {Host:'podman', Network:'podman', Pod:'podman', Container:'podman',
      Datastore:'db', Database:'db', Table:'db', ScheduledJob:'cron',
      Route:'traefik', Middleware:'traefik', Datasource:'grafana', Dashboard:'grafana', McpServer:'mcp'} AS owner
UNWIND keys(owner) AS label
WITH run, label, owner[label] AS src, d WHERE d.sources[owner[label]].ok
MATCH (n) WHERE label IN labels(n) AND (n.seen IS NULL OR n.seen < run)
WITH label, collect(n) AS stale
FOREACH (n IN stale | DETACH DELETE n)
RETURN label AS deleted_label, size(stale) AS deleted;

CALL apoc.load.json('file:///infra.json') YIELD value AS d
WITH d, datetime(d.run) AS run
MATCH ()-[r]->() WHERE r.src IS NOT NULL AND r.seen < run AND d.sources[r.src].ok
WITH collect(r) AS stale
FOREACH (r IN stale | DELETE r)
RETURN size(stale) AS deleted_relationships;

// ---------- run marker ----------
CALL apoc.load.json('file:///infra.json') YIELD value AS d
MERGE (m:CollectorRun {name: 'infra-graph'})
SET m.last_run = datetime(d.run),
    m.sources_ok = [k IN keys(d.sources) WHERE d.sources[k].ok],
    m.sources_failed = [k IN keys(d.sources) WHERE NOT d.sources[k].ok];
