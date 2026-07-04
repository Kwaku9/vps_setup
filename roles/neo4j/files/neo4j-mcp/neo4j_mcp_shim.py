"""neo4j-mcp description shim.

Gives the three mcp-neo4j-cypher tools richer, project-specific descriptions
so an agent knows WHEN to reach for this sessions+infra graph (vs. the
session-recall semantic-search MCP) and HOW to query it — without forking the
upstream package.

Mechanism: monkeypatch ``create_mcp_server`` so that, right after the package
registers its tools, we overwrite their ``.description`` strings; then hand off
to the package's own argv-driven ``main()``. Every transport / host /
allowed-hosts / schema-sample-size flag passes through untouched, and the
package's write-guard, read timeout, and result sanitization are reused
verbatim.

Pinned against mcp-neo4j-cypher==0.6.0 / fastmcp 2.13.x: tools live in
``mcp._tool_manager._tools``; ``.description`` is mutable and surfaces through
``get_tools()`` (verified). If a future bump renames those internals the patch
degrades safely — it logs and serves the stock descriptions rather than
crashing.
"""
import logging

from mcp_neo4j_cypher import main
from mcp_neo4j_cypher import server as _server

log = logging.getLogger("neo4j-mcp-shim")

# Keyed by the base tool name. Namespace prefixes (if ever configured) are
# matched by suffix below, so these still apply under a non-empty --namespace.
DESCRIPTIONS = {
    "read_neo4j_cypher": (
        "Run a read-only Cypher query against the \"sessions\" knowledge graph "
        "— a structured Neo4j mirror of the user's Claude Code history joined "
        "with a live map of the VPS infrastructure. Use this for precise, "
        "structural, or aggregate questions that semantic search can't answer.\n"
        "\n"
        "Two subgraphs:\n"
        "- Session history: (:Session)-[:HAS_MESSAGE]->(:Message)-[:USED_TOOL]->"
        "(:ToolCall)-[:IS_TYPE]->(:ToolType); (:Project)-[:HAS_SESSION]->"
        "(:Session); (:Session)-[:TOUCHED]->(:File); "
        "(:Session)-[:PRODUCED_COMMIT]->(:Commit); "
        "(:Session)-[:SHARES_FILE]->(:Session); (:Session)-[:SPAWNED]->"
        "(:Subagent); (:Session)-[:USED_MODEL]->(:Model); "
        "(:Session)-[:ABOUT]->(:Topic|:Service); plus :Codebase/:Repo. "
        "(~770 sessions, 271k messages, 58k tool calls.)\n"
        "- VPS service map: (:Container)-[:RUNS_ON]->(:Host); :Pod, :Network, "
        ":Route (:ROUTES_TO/:SERVES), :Datastore/:Database, :Middleware, "
        ":External; (:Risk)-[:AFFECTS]->(:Container|:Pod); :DEPENDS_ON / "
        ":CALLS_EXTERNAL edges.\n"
        "\n"
        "Best for: counts & aggregates (\"how many sessions/messages\", \"top "
        "tools\"), \"which sessions touched file X\", git history (:Commit), "
        "cross-session links (:SHARES_FILE), and \"how is the infra wired\" "
        "(containers/routes/deps/risks). Call get_neo4j_schema first if unsure "
        "of labels or relationship directions. For fuzzy \"what did we "
        "discuss/decide/conclude\" recall, use the session-recall MCP's "
        "search_sessions instead — and it's fine to use BOTH for one question "
        "(e.g. search_sessions to find a session, then Cypher to pull its "
        "files/commits/tool usage). Only MATCH/read queries are allowed; pass "
        "query params via `params`."
    ),
    "write_neo4j_cypher": (
        "Run a write Cypher query (CREATE/MERGE/SET/DELETE) against the "
        "sessions+infra knowledge graph. The graph is normally populated by "
        "ingest pipelines, so only write when the user explicitly asks to "
        "modify graph data (e.g. annotate a node, fix a bad edge). For reads "
        "use read_neo4j_cypher; to inspect labels/properties first use "
        "get_neo4j_schema. Only write queries are accepted here."
    ),
    "get_neo4j_schema": (
        "Return the live schema (node labels, their properties with types + "
        "indexed flags, and relationships) of the sessions+infra graph. Call "
        "this before writing Cypher when you're unsure of the exact labels or "
        "relationship directions.\n"
        "\n"
        "IMPORTANT: pass `sample_size` explicitly (e.g. 1000). If the "
        "deployment sets no server default, omitting it injects a literal None "
        "into the underlying APOC call and errors. Use 100 if it times out, or "
        "-1 to sample the whole graph."
    ),
}

_orig_create_mcp_server = _server.create_mcp_server


def _create_mcp_server_with_descriptions(*args, **kwargs):
    mcp = _orig_create_mcp_server(*args, **kwargs)
    try:
        tools = mcp._tool_manager._tools  # name -> FunctionTool
        for tname, tool in tools.items():
            for base, desc in DESCRIPTIONS.items():
                if tname == base or tname.endswith(base):
                    tool.description = desc
                    break
    except Exception as exc:  # pragma: no cover - defensive against pkg bumps
        log.warning("neo4j-mcp shim: could not relabel tools (%s); serving "
                    "stock descriptions", exc)
    return mcp


# server.main() looks up create_mcp_server as a module global, so reassigning
# it on the module makes the patched version take effect at serve time.
_server.create_mcp_server = _create_mcp_server_with_descriptions


if __name__ == "__main__":
    main()
