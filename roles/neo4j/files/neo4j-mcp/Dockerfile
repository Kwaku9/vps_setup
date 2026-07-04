# Neo4j Cypher MCP server — reproduces localhost/neo4j-mcp:latest.
# Just the official mcp-neo4j-cypher package on a slim Python base.
# The run command (--transport http --server-host/--server-port) is supplied
# by the podman_container task, matching the original hand-deployed container.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="neo4j-mcp" \
      org.opencontainers.image.description="mcp-neo4j-cypher MCP server for the service-map graph"

# Pinned to the version captured from the live container for reproducibility.
RUN pip install --no-cache-dir mcp-neo4j-cypher==0.6.0

# Description shim: relabels the 3 tools with project-specific guidance (when to
# use the sessions+infra graph vs. semantic recall, and how to query it) without
# forking the package. It monkeypatches create_mcp_server then calls the stock
# argv-driven main(), so the CMD flags below pass straight through.
COPY neo4j_mcp_shim.py /app/neo4j_mcp_shim.py

# Non-root for K8s-friendliness; the server needs no writable paths.
RUN useradd -r -u 10001 mcp
USER mcp

ENTRYPOINT ["python", "/app/neo4j_mcp_shim.py"]
CMD ["--transport", "http", "--server-host", "0.0.0.0", "--server-port", "8080"]
