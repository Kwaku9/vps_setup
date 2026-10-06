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
        "Read-only Cypher over the user's knowledge graph: every past AI "
        "session (what was done, with which tools, to which files and commits) "
        "joined with a nightly map of the VPS (containers, pods, routes, "
        "databases, jobs, risks) and an index of their code and docs. Use it "
        "for exact, structural or counting questions; for \"what did we "
        "discuss or decide\" use session-recall search_sessions instead, and "
        "combine the two freely (search finds a session_uuid, Cypher pulls its "
        "commands, files and commits).\n"
        "\n"
        "Sessions (2,300+; Session.source = local | vps (Claude Code, "
        "2026-01 onward) | codex (2026-07 onward) | chatgpt (2024-01 to "
        "2025-03, text only, no tool calls)). Key properties: Session.uuid, "
        "title, summary, started_at, status, total_tool_calls, cli_version.\n"
        "- (:Project {display_name})-[:HAS_SESSION]->(:Session)\n"
        "- (:Session)-[:HAS_MESSAGE]->(:Message {role, type, sequence_num, "
        "content_preview})-[:NEXT]->(:Message)\n"
        "- (:Message)-[:USED_TOOL]->(:ToolCall {tool_name, status: success | "
        "error | denied | pending, timestamp})-[:IS_TYPE]->(:ToolType {name})\n"
        "- File edits: (:Session)-[:HAS_ARTIFACT]->(:Artifact {action: "
        "created | modified | deleted, file_path, preview})-[:TOUCHES_FILE]->"
        "(:File {path}). Use THIS path for \"which sessions changed file X\"; "
        "Session-[:TOUCHED]->File is legacy and nearly empty.\n"
        "- (:Session)-[:PRODUCED_COMMIT]->(:Commit {sha, message, "
        "committed_at})<-[:HAS_COMMIT]-(:Repo); (:Session)-[:SPAWNED]->"
        "(:Subagent); (:Session)-[:SHARES_FILE]->(:Session); "
        "(:Session)-[:USED_MODEL]->(:Model). Session-[:ABOUT]->Topic is sparse; "
        "don't rely on it for topic search.\n"
        "\n"
        "Infra (VPS, refreshed nightly): (:Pod)-[:CONTAINS]->(:Container {name, "
        "image, state, ports, memory_limit, oom_killed})-[:RUNS_ON]->(:Host); "
        "(:Container)-[:DEPENDS_ON]->(:Container); (:Route {host, path})"
        "-[:ROUTES_TO]->(:Pod|:Container); (:Container|:Pod)-[:READS|WRITES|"
        "USES_DATABASE]->(:Database)-[:HAS_TABLE]->(:Table); "
        "(:ScheduledJob)-[:RUNS_IN]->(:Host); (:Container)-[:BACKED_UP_BY]->"
        "(:ScheduledJob); (:Risk {severity, title})-[:AFFECTS]->(:Container). "
        "A pod publishes ports for all its members, so check the Pod too.\n"
        "Code and docs: (:CodeProject)-[:HAS_FILE]->(:CodeFile)-[:DEFINES]->"
        "(:Symbol); (:CodeProject)-[:DEPLOYED_AS]->(:Container); "
        "(:Doc)-[:HAS_CLAIM]->(:Claim {status}). The knowledge MCP has "
        "ready-made tools for these, prefer it there.\n"
        "\n"
        "Example: MATCH (s:Session)-[:HAS_ARTIFACT]->(a:Artifact)-"
        "[:TOUCHES_FILE]->(f:File) WHERE f.path ENDS WITH $name RETURN s.uuid, "
        "s.title, a.action, s.started_at ORDER BY s.started_at DESC LIMIT 20\n"
        "\n"
        "Rules: MATCH/read only; pass values via `params`, never string-built; "
        "always LIMIT (Message has ~470k nodes, ToolCall ~116k); infra nodes "
        "describe last night's state, so confirm live before acting. Call "
        "get_neo4j_schema if a label or direction is uncertain."
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
