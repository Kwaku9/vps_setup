"""Session search for the ops dashboard: the same graph + semantic queries that
timeline.aicortex.cloud's timeline-api serves, reachable from ops.aicortex.cloud.

Source of truth for the retrieval logic is
vps_setup/roles/journey-tracker/files/timeline-api/main.py (sync SQL/psycopg2).
This is the asyncpg + neo4j-async port for the dashboard process, which cannot
reach timeline-api (it binds frontend-pod's loopback only). Keep the two in step:
same asymmetric query prefix, same DISTINCT ON max-pool, same redaction list.

Endpoints (prefix /api/timeline):
  /search?q=&k=&project=&since=   semantic search over recall.chunks
  /similar/{uuid}?k=              nearest sessions to this session's centroid
  /session/{uuid}/graph           Neo4j neighbourhood
  /session/{uuid}/transcript      redacted user+assistant excerpt + summary
  /file?path=&k=                  sessions that touched a file
  /health                         backend reachability
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from neo4j import AsyncGraphDatabase

router = APIRouter(prefix="/api/timeline", tags=["timeline-search"])

LITELLM_BASE = os.environ.get("LITELLM_BASE_URL", "http://ai-stack-pod:4000/v1")
LITELLM_KEY = os.environ.get("LITELLM_API_KEY", "")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "embeddinggemma")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j-pod:7687")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "")
PREFETCH_MULT = 20
MAX_K = 40

_neo = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS),
                                 connection_timeout=8, max_connection_lifetime=600)

# ── Redaction (mirror of timeline-api) ────────────────────────────────────
_DENY = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)xox[baprs]-[0-9A-Za-z-]{8,}"),
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),
    re.compile(r"sk-ant-[0-9A-Za-z_-]{20,}"),
    re.compile(r"sk-proj-[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bsk-[0-9A-Za-z]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\b\d{8,10}:AA[0-9A-Za-z_-]{30,}"),
    re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s/@]+):[^\s/@]+@"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
    re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
               r"client[_-]?secret|auth[_-]?token|bearer)\b\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\b(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
]


def redact(text: str | None) -> str:
    if not text:
        return ""
    out = text
    for p in _DENY:
        out = p.sub("[redacted]", out)
    return out


def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return pool


# ── Embedding + search SQL ────────────────────────────────────────────────
def gemma_query(query: str) -> str:
    return f"task: search result | query: {query}"


def vec_literal(vec) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


async def embed_query(query: str):
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            f"{LITELLM_BASE}/embeddings",
            headers={"Authorization": f"Bearer {LITELLM_KEY}"},
            json={"model": GEMMA_MODEL, "input": [gemma_query(query)]},
        )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def _search_sql(project: str | None, since: str | None, exclude: str | None):
    clauses, params = [], []
    params.append(None)  # $1 = query vector literal
    if project:
        params.append(project)
        clauses.append(f"AND c.project = ${len(params)}")
    if since:
        params.append(since)
        clauses.append(f"AND c.ts >= ${len(params)}::timestamptz")
    if exclude:
        params.append(exclude)
        clauses.append(f"AND c.session_uuid <> ${len(params)}")
    params.append(None)  # prefetch
    prefetch_idx = len(params)
    where = "\n        ".join(clauses)
    sql = f"""
    WITH hits AS (
      SELECT c.session_uuid, c.project, c.snippet, c.ts,
             c.embedding <=> $1::vector AS dist
      FROM recall.chunks c
      WHERE TRUE
        {where}
      ORDER BY c.embedding <=> $1::vector
      LIMIT ${prefetch_idx}
    ),
    best AS (
      SELECT DISTINCT ON (h.session_uuid) h.session_uuid, h.project, h.snippet, h.ts, h.dist
      FROM hits h
      ORDER BY h.session_uuid, h.dist
    )
    SELECT b.session_uuid, b.project, b.snippet, b.ts, b.dist,
           COALESCE(NULLIF(ss.one_liner, ''), s.title, b.session_uuid) AS title,
           s.started_at, s.source, s.total_messages, s.pillar_id
    FROM best b
    LEFT JOIN sessions.sessions s ON s.session_uuid = b.session_uuid
    LEFT JOIN sessions.session_summaries ss ON ss.session_uuid = b.session_uuid
    """
    return sql, params


def _shape_hit(r) -> dict[str, Any]:
    when = r["started_at"] or r["ts"]
    return {
        "session_uuid": r["session_uuid"],
        "title": redact(r["title"]),
        "project": r["project"],
        "date": when.date().isoformat() if when else None,
        "snippet": redact((r["snippet"] or "").strip())[:400],
        "score": round(1.0 - float(r["dist"]), 4),
        "source": r["source"],
        "messages": r["total_messages"],
        "pillar_id": r["pillar_id"],
    }


async def _search_rows(conn, qv_literal: str, k: int, project=None, since=None, exclude=None):
    sql, params = _search_sql(project, since, exclude)
    params[0] = qv_literal
    params[-1] = max(k, 1) * PREFETCH_MULT
    rows = await conn.fetch(sql, *params)
    hits = [_shape_hit(r) for r in rows]
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:k]


# ── Routes ────────────────────────────────────────────────────────────────
@router.get("/health")
async def health(request: Request):
    out = {"status": "ok", "postgres": False, "neo4j": False, "embedder": bool(LITELLM_KEY)}
    pool = getattr(request.app.state, "db_pool", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                out["recall_chunks"] = await conn.fetchval("SELECT count(*) FROM recall.chunks")
            out["postgres"] = True
        except Exception as e:  # noqa: BLE001
            out["postgres_error"] = type(e).__name__
    try:
        async with _neo.session() as s:
            rec = await (await s.run("MATCH (s:Session) RETURN count(s) AS c")).single()
            out["sessions_in_graph"] = rec["c"]
            out["neo4j"] = True
    except Exception as e:  # noqa: BLE001
        out["neo4j_error"] = type(e).__name__
    if not (out["postgres"] and out["neo4j"]):
        out["status"] = "degraded"
    return out


@router.get("/search")
async def search(request: Request, q: str = Query(..., min_length=2, max_length=500),
                 k: int = Query(12, ge=1, le=MAX_K), project: str | None = None, since: str | None = None):
    pool = _pool(request)
    t0 = time.time()
    try:
        qv = await embed_query(q)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"embedding unavailable: {type(e).__name__}")
    t1 = time.time()
    async with pool.acquire() as conn:
        hits = await _search_rows(conn, vec_literal(qv), k, project, since)
    return {"query": q, "hits": hits,
            "timing_ms": {"embed": int((t1 - t0) * 1000), "search": int((time.time() - t1) * 1000)}}


@router.get("/similar/{uuid}")
async def similar(request: Request, uuid: str, k: int = Query(8, ge=1, le=MAX_K)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT avg(embedding)::text AS c, count(*) AS n FROM recall.chunks WHERE session_uuid = $1", uuid)
        if not row or not row["c"]:
            return {"session_uuid": uuid, "hits": [], "reason": "no embedded chunks for this session"}
        hits = await _search_rows(conn, row["c"], k, exclude=uuid)
    return {"session_uuid": uuid, "chunks": row["n"], "hits": hits}


GRAPH_META = """
MATCH (s:Session {uuid: $uuid})
OPTIONAL MATCH (p:Project)-[:HAS_SESSION]->(s)
RETURN s.uuid AS uuid, s.title AS title, s.summary AS summary, s.started_at AS started_at,
       s.git_branch AS branch, s.source AS source, s.model AS model,
       s.total_messages AS messages, s.total_tool_calls AS tool_calls,
       p.display_name AS project, p.path AS project_path
"""
GRAPH_MODELS = "MATCH (s:Session {uuid: $uuid})-[:USED_MODEL]->(m:Model) RETURN properties(m) AS props"
GRAPH_COMMITS = """
MATCH (s:Session {uuid: $uuid})-[:PRODUCED_COMMIT]->(c:Commit)
RETURN c.short_hash AS sha, c.message AS message, c.committed_at AS date,
       c.branch AS branch, c.files_changed AS files_changed
ORDER BY c.committed_at
"""
GRAPH_SUBAGENTS = "MATCH (s:Session {uuid: $uuid})-[:SPAWNED]->(sa:Subagent) RETURN count(sa) AS n"
GRAPH_FILES = """
MATCH (s:Session {uuid: $uuid})-[:HAS_ARTIFACT]->(a:Artifact)-[:TOUCHES_FILE]->(f:File)
WITH f.path AS path, count(a) AS touches
ORDER BY touches DESC, path
RETURN path, touches LIMIT 40
"""
GRAPH_NEIGHBORS = """
MATCH (s:Session {uuid: $uuid})-[:HAS_ARTIFACT]->(:Artifact)-[:TOUCHES_FILE]->(f:File)
      <-[:TOUCHES_FILE]-(:Artifact)<-[:HAS_ARTIFACT]-(o:Session)
WHERE o.uuid <> $uuid
WITH o, count(DISTINCT f) AS shared, collect(DISTINCT f.path)[..5] AS sample
ORDER BY shared DESC, o.started_at DESC
LIMIT $k
OPTIONAL MATCH (p:Project)-[:HAS_SESSION]->(o)
RETURN o.uuid AS uuid, coalesce(nullif(o.summary, ''), o.title) AS title,
       o.started_at AS started_at, o.source AS source, p.display_name AS project, shared, sample
"""
GRAPH_TOOLS = """
MATCH (s:Session {uuid: $uuid})-[:HAS_MESSAGE]->(:Message)-[:USED_TOOL]->(tc:ToolCall)-[:IS_TYPE]->(t:ToolType)
WITH t.name AS name, count(tc) AS n ORDER BY n DESC LIMIT 12
RETURN name, n
"""


def _iso(v):
    if v is None:
        return None
    if hasattr(v, "iso_format"):
        try:
            return v.iso_format()
        except Exception:  # noqa: BLE001
            pass
    return str(v)


def _model_name(props: dict) -> str | None:
    for key in ("name", "id", "model", "label"):
        if props.get(key):
            return str(props[key])
    for v in props.values():
        if isinstance(v, str) and v:
            return v
    return None


async def _rows(session, cypher, **params):
    res = await session.run(cypher, **params)
    return await res.data()


@router.get("/session/{uuid}/graph")
async def session_graph(uuid: str, k: int = Query(12, ge=1, le=MAX_K)):
    try:
        async with _neo.session() as s:
            meta_rows = await _rows(s, GRAPH_META, uuid=uuid)
            if not meta_rows:
                raise HTTPException(status_code=404, detail="session not in graph")
            meta = meta_rows[0]
            models = [_model_name(r["props"]) for r in await _rows(s, GRAPH_MODELS, uuid=uuid)]
            commits = [{"sha": r["sha"], "message": redact((r["message"] or "").split("\n")[0][:160]),
                        "date": _iso(r["date"]), "branch": r["branch"], "files_changed": r["files_changed"]}
                       for r in await _rows(s, GRAPH_COMMITS, uuid=uuid)]
            sub = await _rows(s, GRAPH_SUBAGENTS, uuid=uuid)
            files = [{"path": r["path"], "touches": r["touches"]} for r in await _rows(s, GRAPH_FILES, uuid=uuid)]
            neighbors = [{"session_uuid": r["uuid"], "title": redact(r["title"]), "date": _iso(r["started_at"]),
                          "source": r["source"], "project": r["project"], "shared": r["shared"], "sample": r["sample"]}
                         for r in await _rows(s, GRAPH_NEIGHBORS, uuid=uuid, k=k)]
            tools = [{"name": r["name"], "n": r["n"]} for r in await _rows(s, GRAPH_TOOLS, uuid=uuid)]
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"graph unavailable: {type(e).__name__}")
    return {
        "session_uuid": uuid,
        "title": redact(meta["summary"] or meta["title"]),
        "project": meta["project"], "project_path": meta["project_path"],
        "branch": meta["branch"], "source": meta["source"], "started_at": _iso(meta["started_at"]),
        "messages": meta["messages"], "tool_calls": meta["tool_calls"],
        "models": [m for m in models if m] or ([meta["model"]] if meta["model"] else []),
        "commits": commits, "subagents": sub[0]["n"] if sub else 0,
        "files": files, "shared_file_sessions": neighbors, "tools": tools,
    }


@router.get("/session/{uuid}/transcript")
async def transcript(request: Request, uuid: str, max_chars: int = Query(6000, ge=500, le=20000)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        meta = await conn.fetchrow(
            """SELECT s.id, s.title, s.started_at, s.source, s.pillar_id,
                      COALESCE(p.display_name, p.project_path) AS project,
                      ss.one_liner, ss.paragraph
               FROM sessions.sessions s
               LEFT JOIN sessions.projects p ON p.id = s.project_id
               LEFT JOIN sessions.session_summaries ss ON ss.session_uuid = s.session_uuid
               WHERE s.session_uuid = $1""", uuid)
        if not meta:
            raise HTTPException(status_code=404, detail="session not found")
        rows = await conn.fetch(
            """SELECT m.type, m.content_text FROM sessions.messages m
               WHERE m.session_id = $1 AND m.type IN ('user','assistant')
                 AND m.content_text IS NOT NULL AND m.content_text ~ '[^[:space:]]'
               ORDER BY m.sequence_num""", meta["id"])
    turns, used = [], 0
    for r in rows:
        body = r["content_text"].strip()
        if r["type"] == "user" and re.match(r"^\s*(<|\[Request interrupted|Caveat:)", body):
            continue
        chunk = redact(body)[:1500]
        if used + len(chunk) > max_chars:
            chunk = chunk[: max(0, max_chars - used)]
            if chunk:
                turns.append({"role": r["type"], "text": chunk, "truncated": True})
            break
        turns.append({"role": r["type"], "text": chunk})
        used += len(chunk)
    return {
        "session_uuid": uuid,
        "title": redact(meta["one_liner"] or meta["title"]),
        "one_liner": redact(meta["one_liner"]), "paragraph": redact(meta["paragraph"]),
        "project": meta["project"], "source": meta["source"], "pillar_id": meta["pillar_id"],
        "date": meta["started_at"].date().isoformat() if meta["started_at"] else None,
        "turns": turns, "chars": used,
    }


FILE_SESSIONS = """
MATCH (f:File)
WHERE f.path = $path OR f.path ENDS WITH $suffix
WITH f LIMIT 5
MATCH (s:Session)-[:HAS_ARTIFACT]->(a:Artifact)-[:TOUCHES_FILE]->(f)
WITH s, f.path AS path, count(a) AS touches
ORDER BY s.started_at DESC
LIMIT $k
OPTIONAL MATCH (p:Project)-[:HAS_SESSION]->(s)
RETURN s.uuid AS uuid, coalesce(nullif(s.summary, ''), s.title) AS title,
       s.started_at AS started_at, s.source AS source, p.display_name AS project, path, touches
"""


@router.get("/file")
async def file_sessions(path: str = Query(..., min_length=2, max_length=600), k: int = Query(30, ge=1, le=100)):
    suffix = "/" + path.lstrip("/").split("/")[-1] if "/" not in path.strip("/") else path
    try:
        async with _neo.session() as s:
            rows = [{"session_uuid": r["uuid"], "title": redact(r["title"]), "date": _iso(r["started_at"]),
                     "source": r["source"], "project": r["project"], "path": r["path"], "touches": r["touches"]}
                    for r in await _rows(s, FILE_SESSIONS, path=path, suffix=suffix, k=k)]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"graph unavailable: {type(e).__name__}")
    return {"path": path, "sessions": rows}
