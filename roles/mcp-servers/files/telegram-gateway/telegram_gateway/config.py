import os


TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_WEBHOOK_SECRET: str = os.environ["TELEGRAM_WEBHOOK_SECRET"]
TELEGRAM_ALLOWED_USER_IDS: set[int] = {
    int(uid.strip())
    for uid in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
}

# Approval workflow — users who can approve/deny actions via inline buttons.
# Falls back to TELEGRAM_ALLOWED_USER_IDS if not set.
_approver_raw = os.environ.get("APPROVER_ALLOW_LIST", "")
APPROVER_ALLOW_LIST: set[int] = {
    int(uid.strip()) for uid in _approver_raw.split(",") if uid.strip()
} or TELEGRAM_ALLOWED_USER_IDS

# HMAC secret for signing callback_data in approval buttons.
# Falls back to AUTH_TOKEN so no extra secret is needed by default.
APPROVAL_HMAC_SECRET: str = os.environ.get("APPROVAL_HMAC_SECRET", "")

# Approval timeout in minutes (pending approvals expire after this)
APPROVAL_TIMEOUT_MINUTES: int = int(os.environ.get("APPROVAL_TIMEOUT_MINUTES", "10"))

DB_HOST: str = os.environ.get("DB_HOST", "shared-db-pod")
DB_PORT: int = int(os.environ.get("DB_PORT", "5432"))
DB_NAME: str = os.environ.get("DB_NAME", "enterprise")
DB_USER: str = os.environ.get("DB_USER", "postgres")
DB_PASSWORD: str = os.environ.get("DB_PASSWORD", "")

# LiteLLM gateway (fallback backend)
LITELLM_BASE_URL: str = os.environ.get("LITELLM_BASE_URL", "http://ai-stack-pod:4000")
LITELLM_API_KEY: str = os.environ.get("LITELLM_API_KEY", "")
LITELLM_DEFAULT_MODEL: str = os.environ.get("LITELLM_DEFAULT_MODEL", "claude-haiku-4-5")

# Claude Code CLI (default backend)
CLAUDE_CLI_PATH: str = os.environ.get("CLAUDE_CLI_PATH", "/usr/local/bin/claude")
CLAUDE_CLI_TIMEOUT: int = int(os.environ.get("CLAUDE_CLI_TIMEOUT", "300"))
# Optional: give the in-container Claude CLI a dedicated MCP config (e.g. the neo4j
# service-map graph at neo4j-pod:8080). Empty = no extra MCP servers.
# CLAUDE_ALLOWED_TOOLS is a comma-separated allowlist so headless `claude -p` may
# call those MCP tools without an interactive approval prompt.
CLAUDE_MCP_CONFIG: str = os.environ.get("CLAUDE_MCP_CONFIG", "")
CLAUDE_ALLOWED_TOOLS: str = os.environ.get("CLAUDE_ALLOWED_TOOLS", "")

OTEL_EXPORTER_OTLP_ENDPOINT: str = os.environ.get(
    "OTEL_EXPORTER_OTLP_ENDPOINT", "http://monitoring-pod:4318"
)

AUTH_TOKEN: str = os.environ.get("AUTH_TOKEN", "")

# --- Coder bot (BOT_MODE=coder) ---
# Selects the bot persona/runtime. "gateway" = existing ops/APM bot (default,
# unchanged). "coder" = autonomous streaming coding agent with approval gating.
BOT_MODE: str = os.environ.get("BOT_MODE", "gateway")

# Model the coder's headless `claude -p` runs as. Coding-only, no agent split.
CODER_MODEL: str = os.environ.get("CODER_MODEL", "claude-opus-4-8")

# Generated at startup (Task 7): an --mcp-config file pointing the in-container
# CLI at this app's own permission-prompt MCP tool.
CODER_APPROVER_MCP_CONFIG: str = os.environ.get(
    "CODER_APPROVER_MCP_CONFIG", "/app/coder-approver-mcp.json"
)

# Soft "still working" heartbeat cadence, minutes. 0 disables.
CODER_HEARTBEAT_MINUTES: int = int(os.environ.get("CODER_HEARTBEAT_MINUTES", "3"))

# Tools the coder may run WITHOUT an approval prompt (read-only).
CODER_AUTO_ALLOW_TOOLS: str = os.environ.get(
    "CODER_AUTO_ALLOW_TOOLS", "Read,Grep,Glob"
)

# --- OWUI coder (BOT_MODE=owui) ---
# Resumes real Claude Code sessions from OpenWebUI. Tools the OWUI coder may run
# without an approval round-trip (read-only); everything else is hook-gated and
# surfaced as a native OpenWebUI confirmation.
OWUI_AUTO_ALLOW_TOOLS: str = os.environ.get(
    "OWUI_AUTO_ALLOW_TOOLS", "Read,Grep,Glob,TodoWrite"
)
# Pending OWUI approvals expire after this many minutes (fail-closed).
OWUI_APPROVAL_TIMEOUT_MINUTES: int = int(
    os.environ.get("OWUI_APPROVAL_TIMEOUT_MINUTES", "10")
)

# --- Historian persona (BOT_MODE=owui, persona="historian") ---
# HISTORIAN_MCP_CONFIG points at an ansible-rendered file mounted into the
# container (contains the bearer header for the session-recall HTTP transport).
HISTORIAN_MCP_CONFIG: str = os.environ.get(
    "HISTORIAN_MCP_CONFIG", "/app/historian-mcp.json"
)
# Historian gets ONLY the recall tools — NOT Read/Grep/Glob. owui-coder mounts
# /root/.claude and /workspace, and the tool inputs (past-session transcripts)
# are untrusted; auto-allowing file reads would let a prompt-injection in a
# transcript exfiltrate e.g. /root/.claude.json. The Historian answers purely
# from the DB via MCP, so it needs no filesystem tools. Matches the prompt's
# "ONLY the search_sessions and get_session tools".
HISTORIAN_AUTO_ALLOW_TOOLS: str = os.environ.get(
    "HISTORIAN_AUTO_ALLOW_TOOLS",
    "mcp__session-recall__search_sessions,mcp__session-recall__get_session",
)
HISTORIAN_SYSTEM_PROMPT: str = os.environ.get(
    "HISTORIAN_SYSTEM_PROMPT",
    "You are the Historian. You answer questions about the user's own past "
    "development work using ONLY the search_sessions and get_session tools over "
    "their Claude Code session history. Always cite the session a claim comes "
    "from (its date and project). When a search snippet is too thin to answer, "
    "call get_session to pull the fuller transcript. If the sessions do not "
    "cover the question, say so plainly — never invent history.",
)

RATE_LIMIT_PER_MINUTE: int = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "20"))
MCP_SERVER_PORT: int = int(os.environ.get("MCP_SERVER_PORT", "7555"))

# Kokoro TTS (OpenAI-compatible, runs in ai-stack-pod)
KOKORO_TTS_URL: str = os.environ.get("KOKORO_TTS_URL", "http://ai-stack-pod:8880")

# Grafana screenshot rendering
GRAFANA_URL: str = os.environ.get("GRAFANA_URL", "http://monitoring-pod:3000")
GRAFANA_USER: str = os.environ.get("GRAFANA_USER", "admin")
GRAFANA_PASSWORD: str = os.environ.get("GRAFANA_PASSWORD", "")

TELEGRAM_API_BASE: str = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Resolve APPROVAL_HMAC_SECRET after AUTH_TOKEN is available
if not APPROVAL_HMAC_SECRET:
    APPROVAL_HMAC_SECRET = AUTH_TOKEN
