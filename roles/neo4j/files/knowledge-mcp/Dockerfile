FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
# stdio only: Claude Code runs `podman exec -i knowledge-mcp python /app/server.py`.
# The main process just keeps the container alive; no port is opened.
CMD ["sleep", "infinity"]
