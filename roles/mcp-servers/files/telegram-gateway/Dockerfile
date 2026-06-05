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

COPY requirements.txt ./

# Install runtime deps with pip, NOT uv. uv's bundled DNS resolver hangs on this
# host's unreachable IPv6 nameserver (IPv6 disabled), failing every download with
# EAI_AGAIN; pip uses glibc's resolver — the same one apt/npm use successfully in
# this build. requirements.txt is hash-pinned, generated offline from uv.lock by
# gen-requirements.py (exact versions + hashes for the full transitive closure).
# --require-hashes enforces integrity; --no-deps because the file IS the closure.
# Runs on enterprise_network (set in the podman_image task) so DNS resolves and
# downloads route through Squid; the default 10.88.0.0/16 build net is firewalled
# off. --retries/--timeout add resilience for transient blips through the proxy.
RUN pip install --no-cache-dir --require-hashes --no-deps \
        --retries 10 --timeout 60 -r requirements.txt

COPY telegram_gateway/ /app/telegram_gateway/

ENV PYTHONPATH=/app
ENV SHELL=/bin/bash

EXPOSE 7555

HEALTHCHECK --interval=30s --timeout=10s --retries=3     CMD curl -sf http://localhost:7555/health || exit 1

CMD ["python", "-m", "telegram_gateway.main"]
