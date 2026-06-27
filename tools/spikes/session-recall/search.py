from db import vec_literal
from embedders import gemma, nomic
import kwsearch

GEMMA_TABLES = {"useronly": "spike.emb_gemma_useronly", "userasst": "spike.emb_gemma_userasst"}
NOMIC_TABLES = {"useronly": "spike.emb_nomic_useronly", "userasst": "spike.emb_nomic_userasst"}

METHODS = [
    ("gemma", "useronly"), ("gemma", "userasst"),
    ("nomic", "useronly"), ("nomic", "userasst"),
    ("keyword", "useronly"), ("keyword", "userasst"),
]


def _rank_gemma(conn, query, dataset, k):
    qv = gemma.embed_query(query)
    cur = conn.cursor()
    cur.execute(
        f"SELECT session_uuid, MIN(embedding <=> %s::vector) AS d "
        f"FROM {GEMMA_TABLES[dataset]} GROUP BY session_uuid ORDER BY d ASC LIMIT %s",
        (vec_literal(qv), k),
    )
    return [r[0] for r in cur.fetchall()]


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
    if model == "nomic":
        return _rank_nomic(conn, query, dataset, k)
    if model == "keyword":
        return kwsearch.search(conn, query, dataset, k)
    raise ValueError(model)


def session_titles(conn, uuids):
    if not uuids:
        return {}
    cur = conn.cursor()
    cur.execute(
        "SELECT session_uuid, COALESCE(title, session_uuid) FROM sessions.sessions "
        "WHERE session_uuid = ANY(%s)", (list(uuids),))
    return {r[0]: r[1] for r in cur.fetchall()}
