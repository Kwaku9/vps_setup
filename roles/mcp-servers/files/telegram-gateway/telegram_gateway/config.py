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
