# graph_load.py — Stage 3: load the session graph (hard relational + soft Haiku entities)
# into the existing neo4j-db. Purely additive (MERGE only), idempotent, keyed by session_uuid.
# Neo4j bolt creds come from the environment (NEO4J_URI/USER/PASSWORD) — provided at runtime by
# graph-run.sh, which sources the password from Ansible vault. Never read creds from a file here.
import os, argparse
import db
from neo4j import GraphDatabase

DRIVER = GraphDatabase.driver(os.environ["NEO4J_URI"],
                              auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))

# file path lives in sessions.tool_calls.input_json->>'file_path'; commits in git_commits.commit_hash
SQL = """
SELECT ss.session_uuid, ss.project, ss.started_at, ss.summary_text, ss.categories, ss.soft_entities,
       COALESCE((SELECT array_agg(DISTINCT tc.input_json->>'file_path')
                 FROM sessions.tool_calls tc JOIN sessions.sessions s2 ON s2.id=tc.session_id
                 WHERE s2.session_uuid=ss.session_uuid
                   AND tc.input_json->>'file_path' IS NOT NULL), '{}') AS files,
       COALESCE((SELECT array_agg(DISTINCT gc.commit_hash)
                 FROM sessions.git_commits gc JOIN sessions.sessions s3 ON s3.id=gc.session_id
                 WHERE s3.session_uuid=ss.session_uuid
                   AND gc.commit_hash IS NOT NULL), '{}') AS commits
FROM spike.session_summary ss
WHERE ss.model = 'claude-haiku-4-5'
"""

# FOREACH (not UNWIND) so an empty list is a no-op instead of collapsing the row stream.
CYPHER = """
MERGE (s:Session {uuid:$uuid})
  SET s.started_at=$started, s.project=$project, s.summary=$summary, s.categories=$categories
MERGE (pr:Project {name:$project})
MERGE (s)-[:IN_PROJECT]->(pr)
FOREACH (f  IN $files    | MERGE (fl:File   {path:f})  MERGE (s)-[:TOUCHED]->(fl))
FOREACH (ch IN $commits  | MERGE (cm:Commit {sha:ch})  MERGE (s)-[:MADE]->(cm))
FOREACH (sv IN $services | MERGE (svc:Service {name:sv}) MERGE (s)-[:ABOUT]->(svc))
FOREACH (tp IN $topics   | MERGE (tn:Topic  {name:tp}) MERGE (s)-[:ABOUT]->(tn))
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    conn = db.connect(); cur = conn.cursor()
    cur.execute(SQL + (f" LIMIT {int(a.limit)}" if a.limit else ""))
    rows = cur.fetchall(); conn.close()
    print(f"sessions to load: {len(rows)}")
    n = 0
    with DRIVER.session(database="neo4j") as gs:
        for uuid, project, started, summary, cats, ents, files, commits in rows:
            ents = ents or {}
            gs.run(CYPHER, uuid=uuid, started=str(started), project=project or "unknown",
                   summary=summary or "", categories=cats or [],
                   files=[f for f in (files or []) if f],
                   commits=[c for c in (commits or []) if c],
                   services=ents.get("services", []) or [],
                   topics=ents.get("topics", []) or [])
            n += 1
            if n % 100 == 0:
                print(f"  ...{n}")
    DRIVER.close()
    print(f"loaded {n} sessions")

if __name__ == "__main__":
    main()
