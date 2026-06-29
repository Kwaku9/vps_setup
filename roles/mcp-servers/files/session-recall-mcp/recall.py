"""Retrieval core for session-recall-mcp.

Reimplements the spike's proven gemma-512 dense retrieval cleanly for production:
asymmetric query prefix + pgvector cosine over recall.chunks, max-pooled to the
session level. Pure helpers are unit-tested; embed_query / search_sessions /
get_session do the I/O.
"""
import os

import requests

LITELLM_BASE = os.environ.get("LITELLM_BASE_URL", "http://ai-stack-pod:4000/v1")
LITELLM_KEY = os.environ.get("LITELLM_API_KEY", "")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "embeddinggemma")
PREFETCH_MULT = 20  # ANN candidate chunks fetched per requested session


def gemma_query(query):
    # MUST match the index's asymmetric prefix (text_prep.gemma_query in the spike).
    return f"task: search result | query: {query}"


def vec_literal(vec):
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def embed_query(query):
    resp = requests.post(
        f"{LITELLM_BASE}/embeddings",
        headers={"Authorization": f"Bearer {LITELLM_KEY}"},
        json={"model": GEMMA_MODEL, "input": [gemma_query(query)]},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def build_search_sql(project, since):
    """Pure: assemble the search SQL + the filter params actually used.

    ANN-fetches the closest chunks (HNSW), then picks the best chunk per session
    (DISTINCT ON) and joins the human title. Python sorts + truncates to k.
    """
    clauses = []
    params = {}
    if project:
        clauses.append("AND c.project = %(project)s")
        params["project"] = project
    if since:
        clauses.append("AND c.ts >= %(since)s")
        params["since"] = since
    where = "\n            ".join(clauses)
    sql = f"""
        WITH hits AS (
          SELECT c.session_uuid, c.project, c.snippet, c.ts,
                 c.embedding <=> %(qv)s::vector AS dist
          FROM recall.chunks c
          WHERE TRUE
            {where}
          ORDER BY c.embedding <=> %(qv)s::vector
          LIMIT %(prefetch)s
        )
        SELECT DISTINCT ON (h.session_uuid)
               h.session_uuid, h.project, h.snippet, h.ts, h.dist,
               COALESCE(s.title, h.session_uuid) AS title
        FROM hits h
        LEFT JOIN sessions.sessions s ON s.session_uuid = h.session_uuid
        ORDER BY h.session_uuid, h.dist
    """
    return sql, params


def shape_hit(row):
    """Pure: (session_uuid, project, snippet, ts, dist, title) -> result dict."""
    session_uuid, project, snippet, ts, dist, title = row
    return {
        "session_uuid": session_uuid,
        "title": title,
        "project": project,
        "date": ts.date().isoformat() if ts else None,
        "snippet": (snippet or "").strip(),
        "score": round(1.0 - float(dist), 4),
    }


def search_sessions(conn, query, k=8, project=None, since=None):
    qv = embed_query(query)
    sql, params = build_search_sql(project, since)
    params["qv"] = vec_literal(qv)
    params["prefetch"] = max(k, 1) * PREFETCH_MULT
    cur = conn.cursor()
    cur.execute(sql, params)
    hits = [shape_hit(r) for r in cur.fetchall()]
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:k]


def get_session(conn, session_uuid, max_chars=8000):
    cur = conn.cursor()
    cur.execute(
        """SELECT s.title, s.started_at,
                  COALESCE(p.display_name, p.project_path) AS project
           FROM sessions.sessions s
           JOIN sessions.projects p ON p.id = s.project_id
           WHERE s.session_uuid = %s""",
        (session_uuid,),
    )
    meta = cur.fetchone()
    if not meta:
        return {"error": f"session {session_uuid} not found"}
    title, started_at, project = meta
    cur.execute(
        """SELECT m.type, m.content_text
           FROM sessions.messages m
           JOIN sessions.sessions s ON s.id = m.session_id
           WHERE s.session_uuid = %s
             AND m.type IN ('user','assistant')
             AND m.content_text IS NOT NULL
             AND length(trim(m.content_text)) > 0
           ORDER BY m.sequence_num""",
        (session_uuid,),
    )
    parts = [f"{t}: {txt.strip()}" for t, txt in cur.fetchall()]
    return {
        "session_uuid": session_uuid,
        "title": title or session_uuid,
        "project": project,
        "date": started_at.date().isoformat() if started_at else None,
        "transcript": "\n".join(parts)[:max_chars],
    }
