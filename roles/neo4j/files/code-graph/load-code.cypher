// =============================================================================
// code-graph loader — MERGE one indexed root (code-<root>.json) into neo4j-db.
// Run once per root with:  cypher-shell -P 'f => "code-<root>.json"'
//
// Labels owned here (all keyed, all carry root + seen):
//   CodeProject  a root or a bundled component inside it (PART_OF the root)
//   CodeFile     every indexed file            (CodeProject)-[:HAS_FILE]->
//   Symbol       function / class / method     (CodeFile)-[:DEFINES]->
//   Endpoint     http route, websocket, MCP tool/resource/prompt, telegram
//                command, CLI command          (CodeProject)-[:EXPOSES]->,
//                                              -[:DEFINED_IN]->CodeFile, -[:HANDLED_BY]->Symbol
//   Doc          markdown / diagram            -[:DESCRIBES]->CodeProject
// Edges: CodeFile-[:IMPORTS]->CodeFile, Symbol-[:CALLS]->Symbol,
//        CodeProject-[:SUPERSEDED_BY]->CodeProject (dead copy -> live copy).
// Bridges to the other graphs: CodeProject-[:SAME_AS]->Repo (sessions graph),
//        CodeFile-[:SAME_AS]->File (paths sessions touched, any machine),
//        CodeProject-[:DEPLOYED_AS]->Container (bind mounts into the project, or
//        an image named localhost/<component>).
// Reconcile is scoped to this root, so indexing one root never touches another.
// The session labels Project/File/Repo are never written, only linked to.
// =============================================================================

CREATE CONSTRAINT codeproject_key IF NOT EXISTS FOR (n:CodeProject) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT codefile_key    IF NOT EXISTS FOR (n:CodeFile)    REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT symbol_key      IF NOT EXISTS FOR (n:Symbol)      REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT endpoint_key    IF NOT EXISTS FOR (n:Endpoint)    REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT doc_key         IF NOT EXISTS FOR (n:Doc)         REQUIRE n.key IS UNIQUE;
CREATE INDEX codefile_root IF NOT EXISTS FOR (n:CodeFile) ON (n.root);
CREATE INDEX symbol_name   IF NOT EXISTS FOR (n:Symbol)   ON (n.name);
CREATE FULLTEXT INDEX code_search IF NOT EXISTS
  FOR (n:Symbol|Endpoint|Doc|CodeProject|CodeFile)
  ON EACH [n.name, n.qname, n.doc, n.title, n.headings_text, n.rel, n.path, n.summary];

// ---------- projects ----------
CALL apoc.load.json('file:///' + $f) YIELD value AS d
UNWIND d.projects AS p
MERGE (x:CodeProject {key: p.key})
SET x.name = p.name, x.path = p.path, x.root = d.root, x.class = p.class,
    x.superseded_by = p.superseded_by, x.seen = datetime(d.run)
WITH d, p, x WHERE p.parent IS NOT NULL
MATCH (r:CodeProject {key: p.parent})
MERGE (x)-[e:PART_OF]->(r) SET e.seen = datetime(d.run);

// ---------- files ----------
CALL apoc.load.json('file:///' + $f) YIELD value AS d
UNWIND d.files AS f
MATCH (p:CodeProject {key: f.project})
MERGE (x:CodeFile {key: f.key})
SET x.rel = f.rel, x.lang = f.lang, x.sha = f.sha, x.loc = f.loc, x.parse_error = f.error,
    x.last_changed = f.last_changed, x.doc = f.doc, x.root = d.root, x.project = f.project,
    x.path = d.path + '/' + f.rel, x.name = last(split(f.rel, '/')), x.seen = datetime(d.run)
MERGE (p)-[e:HAS_FILE]->(x) SET e.seen = datetime(d.run);

// ---------- symbols ----------
CALL apoc.load.json('file:///' + $f) YIELD value AS d
UNWIND d.symbols AS s
MATCH (fl:CodeFile {key: s.file})
MERGE (x:Symbol {key: s.key})
SET x.qname = s.qname, x.name = s.name, x.kind = s.kind, x.line = s.line, x.end = s.end,
    x.doc = s.doc, x.sig = s.sig, x.exported = s.exported, x.decorators = s.decorators,
    x.root = d.root, x.project = s.project, x.seen = datetime(d.run)
MERGE (fl)-[e:DEFINES]->(x) SET e.seen = datetime(d.run);

// ---------- endpoints ----------
CALL apoc.load.json('file:///' + $f) YIELD value AS d
UNWIND d.endpoints AS ep
MATCH (p:CodeProject {key: ep.project}), (fl:CodeFile {key: ep.file})
MERGE (x:Endpoint {key: ep.key})
SET x.kind = ep.kind, x.method = ep.method, x.name = ep.name, x.path = ep.path, x.line = ep.line,
    x.root = d.root, x.project = ep.project, x.seen = datetime(d.run)
MERGE (p)-[e1:EXPOSES]->(x) SET e1.seen = datetime(d.run)
MERGE (x)-[e2:DEFINED_IN]->(fl) SET e2.seen = datetime(d.run)
WITH d, ep, x WHERE ep.handler IS NOT NULL
MATCH (h:Symbol {key: ep.handler})
MERGE (x)-[e:HANDLED_BY]->(h) SET e.seen = datetime(d.run);

// ---------- imports & calls ----------
CALL apoc.load.json('file:///' + $f) YIELD value AS d
UNWIND d.imports AS i
MATCH (a:CodeFile {key: i.from}), (b:CodeFile {key: i.to})
MERGE (a)-[e:IMPORTS]->(b) SET e.seen = datetime(d.run);

CALL apoc.load.json('file:///' + $f) YIELD value AS d
UNWIND d.calls AS c
MATCH (a:Symbol {key: c.from}), (b:Symbol {key: c.to})
MERGE (a)-[e:CALLS]->(b) SET e.seen = datetime(d.run);

// ---------- docs ----------
CALL apoc.load.json('file:///' + $f) YIELD value AS d
UNWIND d.docs AS doc
MATCH (p:CodeProject {key: doc.project}), (fl:CodeFile {key: doc.key})
MERGE (x:Doc {key: doc.key})
SET x.path = doc.path, x.rel = doc.rel, x.kind = doc.kind, x.title = doc.title,
    x.name = CASE WHEN doc.title = '' THEN last(split(doc.rel, '/')) ELSE doc.title END,
    x.headings = doc.headings, x.headings_text = apoc.text.join(doc.headings, ' | '),
    x.last_changed = doc.last_changed, x.sha = fl.sha, x.root = d.root, x.seen = datetime(d.run)
MERGE (x)-[e1:DESCRIBES]->(p) SET e1.seen = datetime(d.run)
MERGE (x)-[e2:SAME_FILE]->(fl) SET e2.seen = datetime(d.run);

// ---------- bridges ----------
// dead copy -> the component that replaced it ("<root>/<component name>")
CALL apoc.load.json('file:///' + $f) YIELD value AS d
UNWIND d.projects AS p
WITH d, p WHERE p.superseded_by IS NOT NULL
MATCH (x:CodeProject {key: p.key})
MATCH (live:CodeProject {root: split(p.superseded_by, '/')[0], name: split(p.superseded_by, '/')[1]})
MERGE (x)-[e:SUPERSEDED_BY]->(live) SET e.seen = datetime(d.run);

// sessions graph: Repo nodes carry the checkout path
CALL apoc.load.json('file:///' + $f) YIELD value AS d
UNWIND d.projects AS p
MATCH (x:CodeProject {key: p.key})
MATCH (r:Repo) WHERE r.repo_path = p.path OR (p.parent IS NULL AND r.name = p.name)
MERGE (x)-[e:SAME_AS]->(r) SET e.seen = datetime(d.run);

// sessions graph: File paths differ per machine (/workspace/..., /home/general/...),
// so match on "/<root dir name>/<repo-relative path>" suffix.
CALL apoc.load.json('file:///' + $f) YIELD value AS d
WITH d, '/' + last(split(d.path, '/')) + '/' AS anchor
MATCH (sf:File) WHERE sf.path CONTAINS anchor
WITH d, sf, split(sf.path, anchor) AS parts
WITH d, sf, d.root + ':' + parts[size(parts) - 1] AS key
MATCH (cf:CodeFile {key: key})
MERGE (cf)-[e:SAME_AS]->(sf) SET e.seen = datetime(d.run)
RETURN count(e) AS session_file_links;

// infra graph: a container bind-mounting a path inside a project runs that project
CALL apoc.load.json('file:///' + $f) YIELD value AS d
UNWIND d.projects AS p
MATCH (c:Container) WHERE any(m IN c.mounts WHERE m STARTS WITH p.path + ':' OR m STARTS WITH p.path + '/')
MATCH (x:CodeProject {key: p.key})
MERGE (x)-[e:DEPLOYED_AS {via: 'mount'}]->(c) SET e.seen = datetime(d.run)
RETURN count(e) AS mount_deploy_links;

// infra graph: a container running image localhost/<component> runs that component
// (built images, e.g. telegram-gateway -> telegram-gateway, telegram-coder, owui-coder).
// Dead copies never claim a container; the live copy they were superseded by does.
CALL apoc.load.json('file:///' + $f) YIELD value AS d
UNWIND d.projects AS p
WITH d, p WHERE p.class <> 'dead'
MATCH (c:Container) WHERE c.image STARTS WITH 'localhost/' + p.name + ':'
                       OR c.image = 'localhost/' + p.name
MATCH (x:CodeProject {key: p.key})
MERGE (x)-[e:DEPLOYED_AS {via: 'image'}]->(c) SET e.seen = datetime(d.run)
RETURN count(e) AS image_deploy_links;

// ---------- reconcile this root ----------
CALL apoc.load.json('file:///' + $f) YIELD value AS d
WITH d, datetime(d.run) AS run
UNWIND ['CodeProject', 'CodeFile', 'Symbol', 'Endpoint', 'Doc'] AS label
MATCH (n) WHERE label IN labels(n) AND n.root = d.root AND (n.seen IS NULL OR n.seen < run)
WITH label, collect(n) AS stale
FOREACH (n IN stale | DETACH DELETE n)
RETURN label AS deleted_label, size(stale) AS deleted;

CALL apoc.load.json('file:///' + $f) YIELD value AS d
WITH d, datetime(d.run) AS run
MATCH (a)-[e:PART_OF|HAS_FILE|DEFINES|EXPOSES|DEFINED_IN|HANDLED_BY|IMPORTS|CALLS|DESCRIBES|SAME_FILE|SAME_AS|SUPERSEDED_BY|DEPLOYED_AS]->()
WHERE a.root = d.root AND e.seen < run
  // DEPLOYED_AS edges from the doc audit (via 'audit') are owned by load-audit, not this file
  AND (type(e) <> 'DEPLOYED_AS' OR e.via IN ['mount', 'image'])
WITH collect(e) AS stale
FOREACH (e IN stale | DELETE e)
RETURN size(stale) AS deleted_relationships;

