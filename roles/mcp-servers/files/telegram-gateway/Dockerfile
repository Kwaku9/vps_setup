FROM python:3.11-slim-bookworm

WORKDIR /app

# Install curl (healthcheck) + Node.js 22 (Claude CLI runtime) + uv
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl bash ca-certificates gnupg && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main' > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install Claude CLI from npm. The package uses npm optionalDependencies to pick
# a platform-specific binary (-linux-x64 vs -linux-x64-musl). npm's libc detection
# misfires in some buildkit/Debian environments and selects the musl variant,
# which can't run inside a glibc image ("not found" / missing musl interpreter).
# Workaround: explicitly install the glibc package and overwrite the binary
# that install.cjs placed.
RUN npm install -g @anthropic-ai/claude-code @anthropic-ai/claude-code-linux-x64 && \
    ln -sf /usr/bin/claude /usr/local/bin/claude && \
    if ! /usr/local/bin/claude --version >/dev/null 2>&1; then \
        echo "install.cjs linked musl variant — swapping to glibc" && \
        rm -f /usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe && \
        cp /usr/lib/node_modules/@anthropic-ai/claude-code-linux-x64/claude \
           /usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe && \
        chmod +x /usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe; \
    fi && \
    /usr/local/bin/claude --version

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./

ENV UV_CACHE_DIR=/tmp/uv-cache
ENV UV_PYTHON_PREFERENCE=only-system
# Serialize downloads: uv's parallel pypi fetches overwhelm the build sandbox's
# DNS resolver (EAI_AGAIN), even though single lookups succeed. 1 = no bursts.
ENV UV_CONCURRENT_DOWNLOADS=1
# Extra resilience to slow/flaky index responses during resolution.
ENV UV_HTTP_TIMEOUT=120
# --frozen: install straight from uv.lock — no pypi /simple/ index resolution
#   (uv's DNS resolver flakes on those lookups in this build sandbox).
# --no-dev: keep test-only deps (pytest) out of the runtime image.
# NOTE: this build requires IPv4 DNS — the podman_image task passes
#   --dns=1.1.1.1 because the host resolv.conf's IPv6 nameserver is unreachable
#   (IPv6 disabled) and uv's resolver hangs on it.
RUN uv sync --frozen --no-dev

COPY telegram_gateway/ /app/telegram_gateway/

ENV PYTHONPATH=/app
ENV SHELL=/bin/bash

EXPOSE 7555

HEALTHCHECK --interval=30s --timeout=10s --retries=3     CMD curl -sf http://localhost:7555/health || exit 1

CMD ["uv", "run", "--", "python", "-m", "telegram_gateway.main"]
