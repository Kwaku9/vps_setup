from db import vec_literal
from embedders import gemma, nomic
import kwsearch

GEMMA_TABLES = {"useronly": "spike.emb_gemma_useronly", "userasst": "spike.emb_gemma_userasst"}
GEMMA512_TABLES = {"useronly": "spike.emb_gemma512_useronly", "userasst": "spike.emb_gemma512_userasst"}
NOMIC_TABLES = {"useronly": "spike.emb_nomic_useronly", "userasst": "spike.emb_nomic_userasst"}

METHODS = [
    ("gemma", "useronly"), ("gemma", "userasst"),
    ("gemma512", "useronly"), ("gemma512", "userasst"),
    ("nomic", "useronly"), ("nomic", "userasst"),
    ("keyword", "useronly"), ("keyword", "userasst"),
    ("hybrid", "useronly"), ("hybrid", "userasst"),
    ("graphrag", "useronly"), ("graphrag", "userasst"),
]


def _rank_gemma(conn, query, dataset, k, tables=GEMMA_TABLES):
    qv = gemma.embed_query(query)
    cur = conn.cursor()
    cur.execute(
        f"SELECT session_uuid, MIN(embedding <=> %s::vector) AS d "
        f"FROM {tables[dataset]} GROUP BY session_uuid ORDER BY d ASC LIMIT %s",
        (vec_literal(qv), k),
    )
    return [r[0] for r in cur.fetchall()]


def _rrf(rankings, k=60):
    # Reciprocal-rank fusion: sum 1/(k+rank) across each method's ranked list.
    scores = {}
    for ranked in rankings:
        for rank_pos, uuid in enumerate(ranked, start=1):
            scores[uuid] = scores.get(uuid, 0.0) + 1.0 / (k + rank_pos)
    return [u for u, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


def _rank_hybrid(conn, query, dataset, k):
    dense = _rank_gemma(conn, query, dataset, 20)
    kw = kwsearch.search(conn, query, dataset, 20)
    return _rrf([dense, kw])[:k]


def _rank_nomic(conn, query, dataset, k):
    qv = nomic.embed_query(query)
    cur = conn.cursor()
    cur.execute(
        f"SELECT session_uuid, (embedding <=> %s::vector) AS d "
        f"FROM {NOMIC_TABLES[dataset]} ORDER BY d ASC LIMIT %s",
        (vec_literal(qv), k),
    )
    return [r[0] for r in cur.fetchall()]


def rank(conn, query, model, dataset, k=10):
    if model == "gemma":
        return _rank_gemma(conn, query, dataset, k)
    if model == "gemma512":
        return _rank_gemma(conn, query, dataset, k, tables=GEMMA512_TABLES)
    if model == "nomic":
        return _rank_nomic(conn, query, dataset, k)
    if model == "keyword":
        return kwsearch.search(conn, query, dataset, k)
    if model == "hybrid":
        return _rank_hybrid(conn, query, dataset, k)
    if model == "graphrag":
        import graphrag
        return graphrag.rank(conn, query, dataset, k)
    raise ValueError(model)


def session_titles(conn, uuids):
    if not uuids:
        return {}
    cur = conn.cursor()
    cur.execute(
        "SELECT session_uuid, COALESCE(title, session_uuid) FROM sessions.sessions "
        "WHERE session_uuid = ANY(%s)", (list(uuids),))
    return {r[0]: r[1] for r in cur.fetchall()}
