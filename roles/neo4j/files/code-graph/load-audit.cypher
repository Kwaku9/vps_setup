// =============================================================================
// Doc-audit loader: attach audit facts (audit.json, built by load_audit.py) to
// the code graph. Runs after every load-code pass.
//
//   CodeProject.class/summary/missing_docs  from the audit (overrides projects.yml
//                                            for bundled components)
//   (CodeProject)-[:DEPLOYED_AS {via:'audit'}]->(Container)
//   (Doc)-[:HAS_CLAIM]->(Claim {text, kind, status, evidence})
//   Doc.audit_status   current | partly-stale | stale | unverifiable (as audited)
//   Doc.freshness      'audited'          content unchanged since the audit
//                      'needs-reaudit'    content changed after the audit (sha moved)
//   AuditedProject     audits for paths the indexer does not cover (third-party)
// =============================================================================
CREATE CONSTRAINT claim_key IF NOT EXISTS FOR (n:Claim) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT audited_slug IF NOT EXISTS FOR (n:AuditedProject) REQUIRE n.slug IS UNIQUE;

CALL apoc.load.json('file:///code-audit.json') YIELD value AS d
UNWIND d.projects AS a
WITH d, a WHERE a.key IS NOT NULL
MATCH (p:CodeProject {key: a.key})
SET p.class = coalesce(a.class, p.class), p.class_evidence = a.class_evidence,
    p.summary = a.summary, p.missing_docs = a.missing_docs, p.audited_at = datetime(a.audited_at),
    p.audit_slug = a.slug;

CALL apoc.load.json('file:///code-audit.json') YIELD value AS d
UNWIND d.projects AS a
WITH d, a WHERE a.key IS NULL
MERGE (p:AuditedProject {slug: a.slug})
SET p.name = a.name, p.path = a.path, p.class = a.class, p.summary = a.summary,
    p.missing_docs = a.missing_docs, p.audited_at = datetime(a.audited_at), p.seen = datetime(d.run);

CALL apoc.load.json('file:///code-audit.json') YIELD value AS d
UNWIND d.deployed AS x
MATCH (c:Container {name: x.container})
OPTIONAL MATCH (p:CodeProject {key: x.key})
OPTIONAL MATCH (ap:AuditedProject {slug: x.slug})
WITH d, x, c, coalesce(p, ap) AS src WHERE src IS NOT NULL
MERGE (src)-[e:DEPLOYED_AS {via: 'audit'}]->(c) SET e.evidence = x.evidence, e.seen = datetime(d.run);

// Doc status + freshness. audit_sha is the content hash at audit time: reset it
// whenever a newer audit arrives, keep it otherwise, and compare with the live sha.
CALL apoc.load.json('file:///code-audit.json') YIELD value AS d
UNWIND d.docs AS a
WITH d, a WHERE a.key IS NOT NULL
MATCH (x:Doc {key: a.key})
SET x.audit_sha = CASE WHEN x.audited_at IS NULL OR x.audited_at <> datetime(a.audited_at)
                       THEN x.sha ELSE x.audit_sha END,
    x.audited_at = datetime(a.audited_at), x.audit_status = a.status,
    x.claims_verified = a.n_verified, x.claims_contradicted = a.n_contradicted,
    x.claims_unverifiable = a.n_unverifiable
SET x.freshness = CASE WHEN x.sha = x.audit_sha THEN 'audited' ELSE 'needs-reaudit' END;

CALL apoc.load.json('file:///code-audit.json') YIELD value AS d
UNWIND d.claims AS c
MERGE (k:Claim {key: c.key})
SET k.text = c.text, k.kind = c.kind, k.status = c.status, k.evidence = c.evidence,
    k.doc_path = c.doc_path, k.audited_at = datetime(c.audited_at), k.seen = datetime(d.run)
WITH d, c, k WHERE c.doc_key IS NOT NULL
MATCH (x:Doc {key: c.doc_key})
MERGE (x)-[e:HAS_CLAIM]->(k) SET e.seen = datetime(d.run);

// Docs the indexer does not hold (e.g. /workspace/CLAUDE.md, host-only files):
// keep their claims reachable through a lightweight Doc keyed by absolute path.
CALL apoc.load.json('file:///code-audit.json') YIELD value AS d
UNWIND d.docs AS a
WITH d, a WHERE a.key IS NULL
MERGE (x:Doc {key: 'path:' + a.path})
SET x.path = a.path, x.name = last(split(a.path, '/')), x.kind = a.kind, x.root = '_external',
    x.audit_status = a.status, x.audited_at = datetime(a.audited_at), x.freshness = 'audited',
    x.claims_verified = a.n_verified, x.claims_contradicted = a.n_contradicted,
    x.claims_unverifiable = a.n_unverifiable, x.seen = datetime(d.run)
WITH d, a, x
OPTIONAL MATCH (p:CodeProject {key: a.project_key})
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (x)-[:DESCRIBES]->(p))
WITH d, a, x
MATCH (k:Claim {doc_path: a.path})
MERGE (x)-[e:HAS_CLAIM]->(k) SET e.seen = datetime(d.run);

// Reconcile audit-owned facts that a newer audit set no longer contains.
CALL apoc.load.json('file:///code-audit.json') YIELD value AS d
WITH datetime(d.run) AS run
OPTIONAL MATCH (k:Claim) WHERE k.seen < run
WITH run, collect(k) AS stale
FOREACH (k IN stale | DETACH DELETE k)
WITH run
OPTIONAL MATCH ()-[e:DEPLOYED_AS {via: 'audit'}]->() WHERE e.seen < run
WITH run, collect(e) AS old
FOREACH (e IN old | DELETE e)
WITH run
OPTIONAL MATCH (p:AuditedProject) WHERE p.seen < run
WITH collect(p) AS gone
FOREACH (p IN gone | DETACH DELETE p)
RETURN size(gone) AS removed_audited_projects;
