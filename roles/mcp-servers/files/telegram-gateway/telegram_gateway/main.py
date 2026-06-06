from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Response
from fastmcp import FastMCP

from telegram_gateway.config import AUTH_TOKEN, MCP_SERVER_PORT
from telegram_gateway import db
from telegram_gateway.bot import (
    router as bot_router,
    send_telegram_message,
    send_telegram_audio,
    send_telegram_video,
    send_telegram_voice,
    send_telegram_document,
)
from telegram_gateway.formatter import format_for_telegram, format_stderr
from telegram_gateway.queue import job_queue
from telegram_gateway.tools.send import router as send_router
from telegram_gateway.tools.commands import router as commands_router
from telegram_gateway.tools.permission import router as permission_router
from telegram_gateway.tracing import init_tracing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_listen_task: asyncio.Task | None = None


async def _listen_responses():
    """Background task: listen for pg_notify on 'response_ready' channel
    and deliver responses to Telegram."""
    pool = await db.get_pool()
    conn = await pool.acquire()
    try:
        await conn.add_listener("response_ready", _on_response_notify)
        logger.info("LISTEN response_ready started")
        # Keep alive until cancelled
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await conn.remove_listener("response_ready", _on_response_notify)
    finally:
        await pool.release(conn)


def _on_response_notify(conn, pid, channel, payload):
    """Callback for pg_notify — schedule async delivery."""
    asyncio.create_task(_deliver_response(payload))


async def _deliver_response(payload_str: str):
    """Fetch a response from DB and send it to Telegram.

    Routes to the appropriate Telegram API method based on response_type:
      - audio:    sendAudio (music player UI)
      - video:    sendVideo (inline player)
      - voice:    sendVoice (waveform UI)
      - document: sendDocument (file download)
      - *:        sendMessage (text/code/etc.)

    For media types, 'content' holds the URL or file_id.
    'payload' JSON may contain caption, title, performer metadata.
    """
    try:
        data = json.loads(payload_str)
        response_id = data["response_id"]
        row = await db.get_unsent_response(response_id)
        if not row:
            return

        chat_id = row["telegram_chat_id"]
        response_type = row["response_type"]
        content = row["content"]
        meta = json.loads(row["payload"]) if row["payload"] else {}

        if response_type == "stderr":
            text = format_stderr(content)
            await send_telegram_message(chat_id, text, parse_mode="HTML")
        elif response_type == "approval":
            # Approval messages are sent directly via send_approval_request
            # in bot.py, not through the response pipeline.
            pass
        elif response_type == "audio":
            await send_telegram_audio(
                chat_id=chat_id,
                audio=content,
                caption=meta.get("caption"),
                title=meta.get("title"),
                performer=meta.get("performer"),
            )
        elif response_type == "video":
            await send_telegram_video(
                chat_id=chat_id,
                video=content,
                caption=meta.get("caption"),
            )
        elif response_type == "voice":
            await send_telegram_voice(
                chat_id=chat_id,
                voice=content,
                caption=meta.get("caption"),
            )
        elif response_type == "document":
            await send_telegram_document(
                chat_id=chat_id,
                document=content,
                caption=meta.get("caption"),
            )
        else:
            text = format_for_telegram(content, response_type)
            await send_telegram_message(chat_id, text)

        await db.mark_response_sent(response_id)
        logger.info("Delivered %s response %d to chat %d", response_type, response_id, chat_id)
    except Exception:
        logger.exception("Failed to deliver response: %s", payload_str)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _listen_task
    # Startup
    await db.init_pool()
    from telegram_gateway.config import BOT_MODE, CODER_APPROVER_MCP_CONFIG
    if BOT_MODE == "coder":
        # Approval gating is enforced by the inherited PreToolUse hook
        # (claude-approval-hook.js) in fail-closed mode, NOT a permission-prompt
        # MCP — that approach failed to connect and, worse, failed OPEN. Write an
        # EMPTY mcp-config so the coder's `claude` runs with --strict-mcp-config
        # against a clean MCP surface: no inherited host servers, none added.
        with open(CODER_APPROVER_MCP_CONFIG, "w") as f:
            json.dump({"mcpServers": {}}, f)
        job_queue.semaphore = asyncio.Semaphore(1)  # one coder session at a time
        logger.info("Coder mode: wrote empty mcp-config (hook-gated), concurrency=1")
    elif BOT_MODE == "owui":
        # Same hook-gated, clean-MCP surface as coder; concurrency is bounded
        # per-workspace inside the SSE handler rather than by the job queue.
        with open(CODER_APPROVER_MCP_CONFIG, "w") as f:
            json.dump({"mcpServers": {}}, f)
        logger.info("OWUI mode: empty mcp-config (hook-gated), per-workspace concurrency")
    _listen_task = asyncio.create_task(_listen_responses())
    logger.info("Telegram Gateway started")
    yield
    # Shutdown
    if _listen_task:
        _listen_task.cancel()
        try:
            await _listen_task
        except asyncio.CancelledError:
            pass
    await job_queue.shutdown()
    await db.close_pool()
    logger.info("Telegram Gateway stopped")


app = FastAPI(
    title="Telegram Gateway MCP",
    description="Bidirectional Telegram <-> Claude gateway",
    version="0.1.0",
    lifespan=lifespan,
)

# Init OTEL tracing (non-fatal if collector unreachable)
try:
    init_tracing(app)
except Exception:
    logger.warning("OTEL tracing init failed — continuing without traces")

# Auth middleware for MCP routes (not webhook or health)
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Skip auth for health, webhook, and docs
    if path in ("/health", "/webhook", "/docs", "/openapi.json") or path.startswith("/mcp"):
        return await call_next(request)
    # Check bearer token for all other routes
    if AUTH_TOKEN:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer ") or auth_header[7:] != AUTH_TOKEN:
            return Response(status_code=401, content="Unauthorized")
    return await call_next(request)


# Include routers — these are both FastAPI routes AND MCP tools.
# OWUI mode serves only the session-resume API (+ commands for the hook's
# /get_approval_status poll) and deliberately omits the Telegram routers so its
# Telegram-free /request_approval is the only one mounted.
from telegram_gateway.config import BOT_MODE  # noqa: E402

if BOT_MODE == "owui":
    from telegram_gateway.owui_api import router as owui_router
    app.include_router(owui_router)
    app.include_router(commands_router)
else:
    app.include_router(bot_router)
    app.include_router(send_router)
    app.include_router(commands_router)
    app.include_router(permission_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "telegram-gateway"}


# Create MCP server from FastAPI routes and mount as sub-app on /mcp
mcp = FastMCP.from_fastapi(app=app)
app.mount("/mcp", mcp.http_app())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=MCP_SERVER_PORT, log_level="info")
