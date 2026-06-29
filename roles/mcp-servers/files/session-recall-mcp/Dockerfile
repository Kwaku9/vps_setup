FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Default (container main process) = HTTP transport, keeps the container alive
# so the host can also `podman exec -i ... -e MCP_TRANSPORT=stdio` into it.
ENV MCP_PORT=8970
CMD ["python", "/app/server.py"]
