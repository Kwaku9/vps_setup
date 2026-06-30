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
from mcp.server.transport_security import TransportSecuritySettings

import recall

# FastMCP's streamable-http ships DNS-rebinding protection that only accepts
# localhost/127.0.0.1 Host headers, which 421s the cross-container Host the
# Historian dials (session-recall-mcp:8970). This server is internal-only
# (enterprise_network), bearer-authed (see _run_http), and not browser-facing,
# so that protection is irrelevant here — disable it.
mcp = FastMCP(
    "session-recall",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False),
)


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

    if not AUTH_TOKEN:
        raise SystemExit("session-recall-mcp: AUTH_TOKEN is required for the http transport")

    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("MCP_PORT", "8970"))
    app = mcp.streamable_http_app()

    class BearerAuthASGI:
        # Pure ASGI middleware: check the bearer on the initial HTTP request,
        # then pass the raw ASGI streams through untouched so streamable-HTTP /
        # SSE responses are not buffered or truncated.
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                headers = dict(scope.get("headers") or [])
                auth = headers.get(b"authorization", b"").decode("latin-1")
                if auth != f"Bearer {AUTH_TOKEN}":
                    await send({"type": "http.response.start", "status": 401,
                                "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                    return
            await self.inner(scope, receive, send)

    uvicorn.run(BearerAuthASGI(app), host=mcp.settings.host, port=mcp.settings.port)


if __name__ == "__main__":
    if os.environ.get("MCP_TRANSPORT") == "stdio":
        mcp.run()  # stdio path is tokenless (host-only, via podman exec)
    else:
        _run_http()
