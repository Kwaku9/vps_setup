"""GraphRAG retrieval: pgvector semantic seed -> Neo4j relationship expansion.

The dense seed (gemma over pgvector) finds the semantically-closest sessions; the graph then
pulls in sessions CONNECTED to the seeds by shared files / project — the cross-session
neighbours a pure vector search misses (what 'history across all sessions' questions need).
"""
import requests

import search
from config import NEO4J_URL, NEO4J_USER, NEO4J_PASSWORD

_EXPAND = (
    "MATCH (s1:Session) WHERE s1.uuid IN $seeds "
    "MATCH (s1)-[:HAS_ARTIFACT]->(:Artifact)-[:TOUCHES_FILE]->(f:File)"
    "<-[:TOUCHES_FILE]-(:Artifact)<-[:HAS_ARTIFACT]-(s2:Session) "
    "WHERE NOT s2.uuid IN $seeds "
    "WITH s2.uuid AS u, count(DISTINCT f) AS shared_files "
    "RETURN u, shared_files ORDER BY shared_files DESC LIMIT 30"
)

_EXPAND_PROJECT = (
    "MATCH (p:Project)-[:HAS_SESSION]->(s1:Session) WHERE s1.uuid IN $seeds "
    "MATCH (p)-[:HAS_SESSION]->(s2:Session) WHERE NOT s2.uuid IN $seeds "
    "WITH s2.uuid AS u, count(DISTINCT p) AS shared_proj "
    "RETURN u, shared_proj ORDER BY shared_proj DESC LIMIT 30"
)


def _cypher(statement, params):
    r = requests.post(
        f"{NEO4J_URL}/db/neo4j/tx/commit",
        auth=(NEO4J_USER, NEO4J_PASSWORD),
        headers={"Content-Type": "application/json"},
        json={"statements": [{"statement": statement, "parameters": params}]},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return [row["row"] for row in data["results"][0]["data"]]


def rank(conn, query, dataset, k=10):
    # 1. dense semantic seed (pgvector / gemma)
    seeds = search._rank_gemma(conn, query, dataset, 5)
    if not seeds:
        return []
    # 2. graph expansion: sessions connected to the seeds (file shares weighted over project shares)
    score = {}
    for u, sf in _cypher(_EXPAND, {"seeds": seeds}):
        score[u] = score.get(u, 0.0) + 2.0 * sf
    for u, sp in _cypher(_EXPAND_PROJECT, {"seeds": seeds}):
        score[u] = score.get(u, 0.0) + 1.0 * sp
    expanded = [u for u, _ in sorted(score.items(), key=lambda x: x[1], reverse=True)]
    # 3. seeds first (in semantic order), then graph-connected sessions
    out = list(seeds)
    for u in expanded:
        if u not in out:
            out.append(u)
    return out[:k]
