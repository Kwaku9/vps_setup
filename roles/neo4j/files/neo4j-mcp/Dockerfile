# Neo4j Cypher MCP server — reproduces localhost/neo4j-mcp:latest.
# Just the official mcp-neo4j-cypher package on a slim Python base.
# The run command (--transport http --server-host/--server-port) is supplied
# by the podman_container task, matching the original hand-deployed container.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="neo4j-mcp" \
      org.opencontainers.image.description="mcp-neo4j-cypher MCP server for the service-map graph"

# Pinned to the version captured from the live container for reproducibility.
RUN pip install --no-cache-dir mcp-neo4j-cypher==0.6.0

# Non-root for K8s-friendliness; the server needs no writable paths.
RUN useradd -r -u 10001 mcp
USER mcp

ENTRYPOINT ["mcp-neo4j-cypher"]
CMD ["--transport", "http", "--server-host", "0.0.0.0", "--server-port", "8080"]
