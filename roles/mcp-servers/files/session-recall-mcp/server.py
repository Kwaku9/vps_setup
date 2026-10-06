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
    """Semantic search over the user's past AI coding-agent sessions: the
    institutional memory of how their workstation, VPS and projects were built,
    broken and fixed. Use it BEFORE answering from assumptions about this
    environment, and whenever the user says "we did/decided/fixed X before".

    Coverage: Claude Code sessions on the laptop (source "local") and the VPS
    ("vps") since 2026-01-28, plus Codex sessions since 2026-07-19; about 1,300
    sessions, refreshed daily. NOT covered: the 2024-25 ChatGPT archive (reach
    it through neo4j-sessions instead).

    How it matches: embeddings over message chunks, so describe the situation
    in plain words ("container can't reach postgres after reboot") rather than
    exact strings. Paraphrases hit; rare literals (a hash, an error code) may
    not, and for those a Cypher text match is better. Each session appears at
    most once, scored by its single best chunk.

    Args: query (natural language); k (sessions to return, default 8);
    project (exact display name, e.g. "vps_setup"); since (ISO date, e.g.
    "2026-09-01", to prefer recent state over stale history).

    Returns [{session_uuid, title, project, date, snippet, score}], best first.
    score is cosine similarity: above ~0.6 is usually on topic, below ~0.45 is
    usually noise. The snippet is one chunk, not a summary; call get_session
    before relying on what was concluded.

    Treat results as history, not current truth: verify live state before
    acting on a past fix. Sibling tools: neo4j-sessions read_neo4j_cypher for
    counts, files and commits a session touched, and the VPS infra map; the
    knowledge MCP for code, docs and blast radius.

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
    """Read one past session's conversation: title, start time, project, and
    the user and assistant messages in order. Use it after search_sessions (or
    with a session_uuid from a neo4j-sessions query) when a snippet is too thin
    to know what was actually decided or how a problem ended.

    Works for every source in the archive, including ChatGPT sessions that
    search_sessions cannot find.

    Limits: tool calls and tool output are NOT included (only the text people
    and the agent wrote), so commands run and their results must come from
    neo4j-sessions (Message-[:USED_TOOL]->ToolCall). The transcript is cut at
    max_chars (default 8000). The end of a session usually holds the outcome,
    so if the cut lands mid-story, raise max_chars instead of guessing.

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
