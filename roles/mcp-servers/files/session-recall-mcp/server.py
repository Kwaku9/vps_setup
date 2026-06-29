"""session-recall-mcp — retrieval tools over recall.chunks.

Two transports from one codebase:
  * stdio  (MCP_TRANSPORT=stdio) — host `claude` connects via `podman exec -i`.
  * http   (default)             — the in-container Historian dials it cross-pod
                                    at http://session-recall-mcp:$MCP_PORT/mcp.

Retrieval only: tools return evidence (passages + which session), never prose.
"""
import os

import psycopg2
from mcp.server.fastmcp import FastMCP

import recall

mcp = FastMCP("session-recall")


def _conn():
    conn = psycopg2.connect()  # PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE
    conn.autocommit = True
    return conn


@mcp.tool()
def search_sessions(query: str, k: int = 8, project: str | None = None,
                    since: str | None = None) -> list:
    """Search the user's past Claude Code sessions semantically.

    Returns up to `k` best-matching sessions as
    {session_uuid, title, project, date, snippet, score}, highest score first.
    Optional `project` (exact display name) and `since` (ISO date) pre-filter.
    On failure returns [{"error": "..."}]; no matches returns []."""
    try:
        conn = _conn()
        try:
            return recall.search_sessions(conn, query, k=k, project=project, since=since)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 — surface a relayable error, never crash the tool
        return [{"error": f"{type(e).__name__}: {e}"}]


@mcp.tool()
def get_session(session_uuid: str, max_chars: int = 8000) -> dict:
    """Fetch one past session's title, date, project, and a trimmed
    user+assistant transcript — for when a search snippet is too thin to answer.
    On failure or unknown uuid returns {"error": "..."}."""
    try:
        conn = _conn()
        try:
            return recall.get_session(conn, session_uuid, max_chars=max_chars)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "")


def _run_http():
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.headers.get("authorization", "") != f"Bearer {AUTH_TOKEN}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("MCP_PORT", "8970"))
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware)
    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port)


if __name__ == "__main__":
    if os.environ.get("MCP_TRANSPORT") == "stdio":
        mcp.run()  # stdio path is tokenless (host-only, via podman exec)
    else:
        if not AUTH_TOKEN:
            raise SystemExit("session-recall-mcp: AUTH_TOKEN is required for the http transport")
        _run_http()
