FROM python:3.11-slim-bookworm

WORKDIR /app

# Install curl (healthcheck) + Node.js 22 (Claude CLI runtime) + uv
RUN apt-get update &&     apt-get install -y --no-install-recommends curl bash ca-certificates gnupg &&     mkdir -p /etc/apt/keyrings &&     curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg &&     echo 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main' > /etc/apt/sources.list.d/nodesource.list &&     apt-get update &&     apt-get install -y --no-install-recommends nodejs &&     rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./

ENV UV_CACHE_DIR=/tmp/uv-cache
ENV UV_PYTHON_PREFERENCE=only-system
RUN uv sync

COPY telegram_gateway/ /app/telegram_gateway/

ENV PYTHONPATH=/app
ENV SHELL=/bin/bash

EXPOSE 7555

HEALTHCHECK --interval=30s --timeout=10s --retries=3     CMD curl -sf http://localhost:7555/health || exit 1

CMD ["uv", "run", "--", "python", "-m", "telegram_gateway.main"]
