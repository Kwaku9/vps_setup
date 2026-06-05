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

COPY pyproject.toml ./

# Install runtime deps with pip, NOT uv. uv's bundled DNS resolver hangs on this
# host's unreachable IPv6 nameserver (IPv6 disabled), failing every download with
# EAI_AGAIN; pip uses glibc's resolver — the same one apt/npm use successfully in
# this build. Deps are read from pyproject at build time, so there's no
# hand-maintained requirements file to drift.
RUN python -c "import tomllib; open('/tmp/requirements.txt','w').write(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" && \
    pip install --no-cache-dir -r /tmp/requirements.txt

COPY telegram_gateway/ /app/telegram_gateway/

ENV PYTHONPATH=/app
ENV SHELL=/bin/bash

EXPOSE 7555

HEALTHCHECK --interval=30s --timeout=10s --retries=3     CMD curl -sf http://localhost:7555/health || exit 1

CMD ["python", "-m", "telegram_gateway.main"]
