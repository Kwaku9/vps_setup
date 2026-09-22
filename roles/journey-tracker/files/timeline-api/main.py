"""timeline-api — graph + semantic query service for timeline.aicortex.cloud.

Runs INSIDE frontend-pod next to the journey-tracker nginx and binds loopback
only (127.0.0.1:8080 in the pod's shared network namespace). nginx proxies
`location /api/` to it; no host port is published and no other container can
reach it. The public hostname is gated by Cloudflare Access, so the browser →
nginx → here path inherits that login. Outbound it talks to shared-db-pod
(Postgres), neo4j-pod and ai-stack-pod over enterprise_network like every other
internal service.

Endpoints (all GET, JSON):
  /api/health                          liveness + backend reachability
  /api/search?q=&k=&project=&since=    semantic search over recall.chunks
  /api/similar/{uuid}?k=               sessions nearest to this session's centroid
  /api/session/{uuid}/graph            Neo4j neighborhood (project, commits, files,
                                       shared-file sessions, subagents, models)
  /api/session/{uuid}/transcript       redacted user+assistant excerpt + summary
  /api/file?path=&k=                   sessions that touched a file (Neo4j)

Retrieval reproduces session-recall-mcp/recall.py exactly (same asymmetric query
prefix, same DISTINCT ON max-pool) so results here match the MCP tool.

Everything text-shaped that leaves this service passes through `redact()`, a
value-shape deny list (keys, tokens, JWTs, creds-in-URIs, private IPs). The
corpus has held pasted credentials before; the timeline must never re-publish one.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

import psycopg2
import psycopg2.extras
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from neo4j import GraphDatabase

app = FastAPI(title="timeline-api", docs_url=None, redoc_url=None, openapi_url=None)

LITELLM_BASE = os.environ.get("LITELLM_BASE_URL", "http://ai-stack-pod:4000/v1")
LITELLM_KEY = os.environ.get("LITELLM_API_KEY", "")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "embeddinggemma")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j-pod:7687")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "")
PREFETCH_MULT = 20
MAX_K = 40

_neo = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS),
                            connection_timeout=8, max_connection_lifetime=600)


# ── Redaction ─────────────────────────────────────────────────────────────
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
    re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),  # tailnet CGNAT
]


def redact(text: str | None) -> str:
    if not text:
        return ""
    out = text
    for p in _DENY:
        out = p.sub("[redacted]", out)
    return out


# ── Postgres ──────────────────────────────────────────────────────────────
def _pg():
    conn = psycopg2.connect(connect_timeout=8)  # PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE
    conn.autocommit = True
    return conn


def gemma_query(query: str) -> str:
    return f"task: search result | query: {query}"


def vec_literal(vec) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def embed_query(query: str):
    resp = requests.post(
        f"{LITELLM_BASE}/embeddings",
        headers={"Authorization": f"Bearer {LITELLM_KEY}"},
        json={"model": GEMMA_MODEL, "input": [gemma_query(query)]},
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


SEARCH_SQL = """
    WITH hits AS (
      SELECT c.session_uuid, c.project, c.snippet, c.ts,
             c.embedding <=> %(qv)s::vector AS dist
      FROM recall.chunks c
      WHERE TRUE
        {where}
      ORDER BY c.embedding <=> %(qv)s::vector
      LIMIT %(prefetch)s
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


def _shape_hit(row) -> dict[str, Any]:
    (uuid, project, snippet, ts, dist, title, started_at, source, total_messages, pillar_id) = row
    return {
        "session_uuid": uuid,
        "title": redact(title),
        "project": project,
        "date": (started_at or ts).date().isoformat() if (started_at or ts) else None,
        "snippet": redact((snippet or "").strip())[:400],
        "score": round(1.0 - float(dist), 4),
        "source": source,
        "messages": total_messages,
        "pillar_id": pillar_id,
    }


def _search_rows(conn, qv_literal: str, k: int, project: str | None, since: str | None,
                 exclude_uuid: str | None = None):
    clauses, params = [], {"qv": qv_literal, "prefetch": max(k, 1) * PREFETCH_MULT}
    if project:
        clauses.append("AND c.project = %(project)s")
        params["project"] = project
    if since:
        clauses.append("AND c.ts >= %(since)s")
        params["since"] = since
    if exclude_uuid:
        clauses.append("AND c.session_uuid <> %(exclude)s")
        params["exclude"] = exclude_uuid
    sql = SEARCH_SQL.format(where="\n        ".join(clauses))
    cur = conn.cursor()
    cur.execute(sql, params)
    hits = [_shape_hit(r) for r in cur.fetchall()]
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:k]


# ── Routes ────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    out = {"status": "ok", "postgres": False, "neo4j": False, "ts": int(time.time())}
    try:
        conn = _pg()
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM recall.chunks")
            out["recall_chunks"] = cur.fetchone()[0]
            out["postgres"] = True
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        out["postgres_error"] = type(e).__name__
    try:
        with _neo.session() as s:
            out["sessions_in_graph"] = s.run("MATCH (s:Session) RETURN count(s) AS c").single()["c"]
            out["neo4j"] = True
    except Exception as e:  # noqa: BLE001
        out["neo4j_error"] = type(e).__name__
    if not (out["postgres"] and out["neo4j"]):
        out["status"] = "degraded"
    return out


@app.get("/api/search")
def search(q: str = Query(..., min_length=2, max_length=500),
           k: int = Query(12, ge=1, le=MAX_K),
           project: str | None = None, since: str | None = None):
    t0 = time.time()
    try:
        qv = embed_query(q)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"embedding unavailable: {type(e).__name__}")
    t1 = time.time()
    conn = _pg()
    try:
        hits = _search_rows(conn, vec_literal(qv), k, project, since)
    finally:
        conn.close()
    return {"query": q, "hits": hits, "timing_ms": {"embed": int((t1 - t0) * 1000),
                                                    "search": int((time.time() - t1) * 1000)}}


@app.get("/api/similar/{uuid}")
def similar(uuid: str, k: int = Query(8, ge=1, le=MAX_K)):
    """Sessions nearest to the centroid of this session's own chunks. No LLM call:
    pure pgvector, so it works even when the embedder is down."""
    conn = _pg()
    try:
        cur = conn.cursor()
        # avg() over one session's chunks (tens to a few hundred rows). This is an
        # aggregate, not a GROUP BY on the vector column, so it is cheap and safe.
        cur.execute("SELECT avg(embedding)::text, count(*) FROM recall.chunks WHERE session_uuid = %s", (uuid,))
        row = cur.fetchone()
        if not row or not row[0]:
            return {"session_uuid": uuid, "hits": [], "reason": "no embedded chunks for this session"}
        centroid, n = row
        hits = _search_rows(conn, centroid, k, None, None, exclude_uuid=uuid)
    finally:
        conn.close()
    return {"session_uuid": uuid, "chunks": n, "hits": hits}


GRAPH_META = """
MATCH (s:Session {uuid: $uuid})
OPTIONAL MATCH (p:Project)-[:HAS_SESSION]->(s)
RETURN s.uuid AS uuid, s.title AS title, s.summary AS summary, s.started_at AS started_at,
       s.git_branch AS branch, s.source AS source, s.model AS model,
       s.total_messages AS messages, s.total_tool_calls AS tool_calls,
       p.display_name AS project, p.path AS project_path
"""
GRAPH_MODELS = """
MATCH (s:Session {uuid: $uuid})-[:USED_MODEL]->(m:Model)
RETURN properties(m) AS props
"""
GRAPH_COMMITS = """
MATCH (s:Session {uuid: $uuid})-[:PRODUCED_COMMIT]->(c:Commit)
RETURN c.short_hash AS sha, c.message AS message, c.committed_at AS date,
       c.branch AS branch, c.files_changed AS files_changed
ORDER BY c.committed_at
"""
GRAPH_SUBAGENTS = """
MATCH (s:Session {uuid: $uuid})-[:SPAWNED]->(sa:Subagent)
RETURN count(sa) AS n
"""
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
       o.started_at AS started_at, o.source AS source, p.display_name AS project,
       shared, sample
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


@app.get("/api/session/{uuid}/graph")
def session_graph(uuid: str, k: int = Query(12, ge=1, le=MAX_K)):
    try:
        with _neo.session() as s:
            meta = s.run(GRAPH_META, uuid=uuid).single()
            if meta is None:
                raise HTTPException(status_code=404, detail="session not in graph")
            models = [_model_name(r["props"]) for r in s.run(GRAPH_MODELS, uuid=uuid)]
            commits = [{"sha": r["sha"], "message": redact((r["message"] or "").split("\n")[0][:160]),
                        "date": _iso(r["date"]), "branch": r["branch"], "files_changed": r["files_changed"]}
                       for r in s.run(GRAPH_COMMITS, uuid=uuid)]
            subagents = s.run(GRAPH_SUBAGENTS, uuid=uuid).single()["n"]
            files = [{"path": r["path"], "touches": r["touches"]} for r in s.run(GRAPH_FILES, uuid=uuid)]
            neighbors = [{"session_uuid": r["uuid"], "title": redact(r["title"]), "date": _iso(r["started_at"]),
                          "source": r["source"], "project": r["project"], "shared": r["shared"],
                          "sample": r["sample"]}
                         for r in s.run(GRAPH_NEIGHBORS, uuid=uuid, k=k)]
            tools = [{"name": r["name"], "n": r["n"]} for r in s.run(GRAPH_TOOLS, uuid=uuid)]
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"graph unavailable: {type(e).__name__}")
    return {
        "session_uuid": uuid,
        "title": redact(meta["summary"] or meta["title"]),
        "project": meta["project"],
        "project_path": meta["project_path"],
        "branch": meta["branch"],
        "source": meta["source"],
        "started_at": _iso(meta["started_at"]),
        "messages": meta["messages"],
        "tool_calls": meta["tool_calls"],
        "models": [m for m in models if m] or ([meta["model"]] if meta["model"] else []),
        "commits": commits,
        "subagents": subagents,
        "files": files,
        "shared_file_sessions": neighbors,
        "tools": tools,
    }


@app.get("/api/session/{uuid}/transcript")
def transcript(uuid: str, max_chars: int = Query(6000, ge=500, le=20000)):
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT s.id, s.title, s.started_at, s.source, s.pillar_id,
                      COALESCE(p.display_name, p.project_path) AS project,
                      ss.one_liner, ss.paragraph
               FROM sessions.sessions s
               LEFT JOIN sessions.projects p ON p.id = s.project_id
               LEFT JOIN sessions.session_summaries ss ON ss.session_uuid = s.session_uuid
               WHERE s.session_uuid = %s""",
            (uuid,),
        )
        meta = cur.fetchone()
        if not meta:
            raise HTTPException(status_code=404, detail="session not found")
        sid, title, started_at, source, pillar_id, project, one_liner, paragraph = meta
        cur.execute(
            """SELECT m.type, m.content_text
               FROM sessions.messages m
               WHERE m.session_id = %s
                 AND m.type IN ('user','assistant')
                 AND m.content_text IS NOT NULL
                 AND m.content_text ~ '[^[:space:]]'
               ORDER BY m.sequence_num""",
            (sid,),
        )
        turns, used = [], 0
        for t, txt in cur.fetchall():
            body = txt.strip()
            # Skip injected system/tool noise that reads as a user turn.
            if t == "user" and re.match(r"^\s*(<|\[Request interrupted|Caveat:)", body):
                continue
            chunk = redact(body)[:1500]
            if used + len(chunk) > max_chars:
                chunk = chunk[: max(0, max_chars - used)]
                if chunk:
                    turns.append({"role": t, "text": chunk, "truncated": True})
                break
            turns.append({"role": t, "text": chunk})
            used += len(chunk)
    finally:
        conn.close()
    return {
        "session_uuid": uuid,
        "title": redact(one_liner or title),
        "one_liner": redact(one_liner),
        "paragraph": redact(paragraph),
        "project": project,
        "source": source,
        "pillar_id": pillar_id,
        "date": started_at.date().isoformat() if started_at else None,
        "turns": turns,
        "chars": used,
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
       s.started_at AS started_at, s.source AS source, p.display_name AS project,
       path, touches
"""


@app.get("/api/file")
def file_sessions(path: str = Query(..., min_length=2, max_length=600),
                  k: int = Query(30, ge=1, le=100)):
    suffix = "/" + path.lstrip("/").split("/")[-1] if "/" not in path.strip("/") else path
    try:
        with _neo.session() as s:
            rows = [{"session_uuid": r["uuid"], "title": redact(r["title"]), "date": _iso(r["started_at"]),
                     "source": r["source"], "project": r["project"], "path": r["path"], "touches": r["touches"]}
                    for r in s.run(FILE_SESSIONS, path=path, suffix=suffix, k=k)]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"graph unavailable: {type(e).__name__}")
    return {"path": path, "sessions": rows}


@app.exception_handler(Exception)
async def _unhandled(_request, exc):
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}"})
