from __future__ import annotations

import hashlib
import hmac as hmac_mod
import html as html_module
import logging
import os
import re
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Header, Request, Response

from telegram_gateway.config import (
    APPROVAL_HMAC_SECRET,
    APPROVAL_TIMEOUT_MINUTES,
    APPROVER_ALLOW_LIST,
    RATE_LIMIT_PER_MINUTE,
    TELEGRAM_ALLOWED_USER_IDS,
    TELEGRAM_API_BASE,
    TELEGRAM_WEBHOOK_SECRET,
)
from telegram_gateway import db
from telegram_gateway.formatter import (
    chunk_message,
    format_approval_result,
    sanitize_secrets,
    strip_html_tags,
)
from telegram_gateway.queue import job_queue

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory rate limiter: {user_id: [timestamps]}
_rate_limits: dict[int, list[float]] = defaultdict(list)

# Agent type mapping from commands
COMMAND_AGENTS = {
    "/code": "code",
    "/infra": "infra",
    "/trade": "trade",
    "/ask": "ask",
    "/apm": "apm",
}

# Special commands (not agent types)
SPECIAL_COMMANDS = {"/new", "/flyer"}


def _check_rate_limit(user_id: int) -> bool:
    """Return True if the user is within rate limits."""
    now = time.time()
    window_start = now - 60
    # Prune old entries
    _rate_limits[user_id] = [
        ts for ts in _rate_limits[user_id] if ts > window_start
    ]
    if len(_rate_limits[user_id]) >= RATE_LIMIT_PER_MINUTE:
        return False
    _rate_limits[user_id].append(now)
    return True


def _parse_command(text: str) -> tuple[str, str]:
    """Parse a Telegram message into (agent_type, message_body).

    /code write hello world → ("code", "write hello world")
    plain text message → ("ask", "plain text message")
    """
    text = text.strip()
    for cmd, agent in COMMAND_AGENTS.items():
        if text.startswith(cmd):
            body = text[len(cmd):].strip()
            return agent, body if body else "Hello"
    return "ask", text


async def send_telegram_message(
    chat_id: int, text: str, parse_mode: str | None = "HTML"
) -> dict:
    """Send a message via Telegram Bot API."""
    chunks = chunk_message(text)
    result = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for chunk in chunks:
            payload: dict = {"chat_id": chat_id, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            resp = await client.post(
                f"{TELEGRAM_API_BASE}/sendMessage", json=payload
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error("Telegram API error: %s", data)
                # Retry without parse_mode if formatting failed
                if parse_mode:
                    payload.pop("parse_mode")
                    payload["text"] = strip_html_tags(chunk)
                    resp = await client.post(
                        f"{TELEGRAM_API_BASE}/sendMessage", json=payload
                    )
                    data = resp.json()
            result = data
    return result


def _is_url(source: str) -> bool:
    """Check if a source string is an HTTP(S) URL."""
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https")


def _is_local_file(source: str) -> bool:
    """Check if a source string is a local file path."""
    return source.startswith("/") and os.path.isfile(source)


def _guess_filename(source: str) -> str:
    """Extract a filename from a URL or path."""
    parsed = urlparse(source)
    name = os.path.basename(parsed.path) if parsed.path else "media"
    return name or "media"


async def _download_to_temp(url: str) -> str:
    """Download a URL to a temporary file. Returns the temp file path.

    Caller is responsible for deleting the file after use.
    """
    suffix = os.path.splitext(urlparse(url).path)[1] or ""
    fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="tg_media_")
    os.close(fd)
    try:
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(tmp_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
        logger.info("Downloaded %s to %s (%d bytes)", url, tmp_path, os.path.getsize(tmp_path))
        return tmp_path
    except Exception:
        os.unlink(tmp_path)
        raise


async def _send_media(
    method: str,
    media_field: str,
    chat_id: int,
    source: str,
    extra_params: dict | None = None,
) -> dict:
    """Send media via Telegram Bot API with automatic multipart fallback.

    Strategy:
      1. file_id (no slashes, no dots after last slash) → JSON method (instant)
      2. URL → try JSON first (Telegram downloads, <20MB limit)
         → on failure, download locally + multipart upload (<50MB limit)
      3. Local file path → multipart upload directly

    Args:
        method: Telegram API method name (e.g. "sendAudio")
        media_field: Field name for the media (e.g. "audio", "video")
        chat_id: Telegram chat ID
        source: URL, file_id, or local file path
        extra_params: Additional parameters (caption, title, performer, etc.)
    """
    params = extra_params or {}
    api_url = f"{TELEGRAM_API_BASE}/{method}"

    # --- Local file: go straight to multipart ---
    if _is_local_file(source):
        return await _upload_multipart(api_url, media_field, source, chat_id, params)

    # --- URL: try JSON first, fall back to download + multipart ---
    if _is_url(source):
        payload = {"chat_id": chat_id, media_field: source, **params}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(api_url, json=payload)
            data = resp.json()

        if data.get("ok"):
            return data

        error_desc = data.get("description", "")
        logger.warning(
            "Telegram %s URL method failed: %s — falling back to multipart upload",
            method, error_desc,
        )

        # Download and retry via multipart
        tmp_path = None
        try:
            tmp_path = await _download_to_temp(source)
            return await _upload_multipart(api_url, media_field, tmp_path, chat_id, params)
        except Exception:
            logger.exception("Multipart fallback failed for %s", source)
            return data  # Return original error
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # --- file_id: JSON method only ---
    payload = {"chat_id": chat_id, media_field: source, **params}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(api_url, json=payload)
        data = resp.json()
        if not data.get("ok"):
            logger.error("Telegram %s error: %s", method, data)
        return data


async def _upload_multipart(
    api_url: str,
    media_field: str,
    file_path: str,
    chat_id: int,
    params: dict,
) -> dict:
    """Upload a local file to Telegram via multipart form-data (up to 50MB)."""
    filename = _guess_filename(file_path)
    form_data = {"chat_id": str(chat_id)}
    for key, val in params.items():
        if val is not None:
            form_data[key] = str(val)

    with open(file_path, "rb") as f:
        files = {media_field: (filename, f)}
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(api_url, data=form_data, files=files)
            data = resp.json()

    if data.get("ok"):
        logger.info("Multipart upload succeeded: %s (%s)", media_field, filename)
    else:
        logger.error("Multipart upload failed: %s", data)
    return data


async def send_telegram_audio(
    chat_id: int,
    audio: str,
    caption: str | None = None,
    title: str | None = None,
    performer: str | None = None,
) -> dict:
    """Send an audio file via Telegram Bot API (shows music player UI).

    Accepts a URL (auto-downloads if >20MB), file_id, or local file path.
    """
    params: dict = {}
    if caption:
        params["caption"] = caption
    if title:
        params["title"] = title
    if performer:
        params["performer"] = performer
    return await _send_media("sendAudio", "audio", chat_id, audio, params)


async def send_telegram_video(
    chat_id: int,
    video: str,
    caption: str | None = None,
) -> dict:
    """Send a video file via Telegram Bot API (shows inline video player).

    Accepts a URL (auto-downloads if >20MB), file_id, or local file path.
    """
    params: dict = {}
    if caption:
        params["caption"] = caption
    return await _send_media("sendVideo", "video", chat_id, video, params)


async def send_telegram_voice(
    chat_id: int,
    voice: str,
    caption: str | None = None,
) -> dict:
    """Send a voice message via Telegram Bot API (shows waveform UI).

    Accepts a URL (auto-downloads if >20MB), file_id, or local file path.
    """
    params: dict = {}
    if caption:
        params["caption"] = caption
    return await _send_media("sendVoice", "voice", chat_id, voice, params)


async def send_telegram_document(
    chat_id: int,
    document: str,
    caption: str | None = None,
) -> dict:
    """Send a document/file via Telegram Bot API (generic file download).

    Accepts a URL (auto-downloads if >20MB), file_id, or local file path.
    """
    params: dict = {}
    if caption:
        params["caption"] = caption
    return await _send_media("sendDocument", "document", chat_id, document, params)


async def send_telegram_photo(
    chat_id: int,
    photo: str,
    caption: str | None = None,
) -> dict:
    """Send a photo via Telegram Bot API.

    Accepts a local file path, URL, or file_id.
    Shows inline in the chat as a compressed image.
    """
    params: dict = {}
    if caption:
        params["caption"] = caption
    return await _send_media("sendPhoto", "photo", chat_id, photo, params)


def _generate_hmac(approval_id: int) -> str:
    """Generate a truncated HMAC signature for an approval ID."""
    return hmac_mod.new(
        APPROVAL_HMAC_SECRET.encode(),
        str(approval_id).encode(),
        hashlib.sha256,
    ).hexdigest()[:16]


def _verify_hmac(approval_id: int, token: str) -> bool:
    """Verify an HMAC token for an approval ID."""
    expected = _generate_hmac(approval_id)
    return hmac_mod.compare_digest(expected, token)


async def answer_callback_query(
    callback_id: str, text: str = "", show_alert: bool = False
) -> dict:
    """Respond to a Telegram callback query (clears button spinner)."""
    payload: dict = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{TELEGRAM_API_BASE}/answerCallbackQuery", json=payload
        )
        return resp.json()


async def edit_message_text(
    chat_id: int,
    message_id: int,
    text: str,
    parse_mode: str | None = "HTML",
    reply_markup: dict | None = None,
) -> dict:
    """Edit an existing message's text and optionally remove buttons."""
    payload: dict = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{TELEGRAM_API_BASE}/editMessageText", json=payload
        )
        data = resp.json()
        if not data.get("ok"):
            logger.error("editMessageText failed: %s", data)
        return data


async def send_approval_request(
    chat_id: int,
    prompt_text: str,
    approval_id: int,
    hmac_token: str,
    requested_by: str | None = None,
) -> dict:
    """Send a message with Approve/Deny inline keyboard buttons."""
    sanitized = sanitize_secrets(prompt_text)
    escaped = html_module.escape(sanitized)
    if len(escaped) > 3500:
        escaped = escaped[:3500] + "..."
    by_line = f"\nRequested by: @{html_module.escape(requested_by)}" if requested_by else ""
    text = (
        f"<b>Approval Required</b>{by_line}\n\n"
        f"<pre>{escaped}</pre>"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Approve", "callback_data": f"a:{approval_id}:{hmac_token}"},
                {"text": "Deny", "callback_data": f"d:{approval_id}:{hmac_token}"},
            ]
        ]
    }
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": reply_markup,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{TELEGRAM_API_BASE}/sendMessage", json=payload
        )
        data = resp.json()
        if not data.get("ok"):
            logger.error("send_approval_request failed: %s", data)
        return data


async def _handle_callback_query(callback_query: dict) -> dict:
    """Process an inline button press (approval/denial)."""
    callback_id = callback_query["id"]
    from_user = callback_query.get("from", {})
    user_id = from_user["id"]
    username = from_user.get("username") or from_user.get("first_name") or "unknown"
    data_str = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")

    # Validate user is in approver list
    if APPROVER_ALLOW_LIST and user_id not in APPROVER_ALLOW_LIST:
        await answer_callback_query(callback_id, "Unauthorized", show_alert=True)
        return {"ok": True}

    # Parse callback data: "a:{id}:{sig}" or "d:{id}:{sig}"
    parts = data_str.split(":", 2)
    if len(parts) != 3 or parts[0] not in ("a", "d"):
        await answer_callback_query(callback_id, "Invalid action", show_alert=True)
        return {"ok": True}

    action_prefix, approval_id_str, sig = parts
    try:
        approval_id = int(approval_id_str)
    except ValueError:
        await answer_callback_query(callback_id, "Invalid approval ID", show_alert=True)
        return {"ok": True}

    # Verify HMAC
    if not _verify_hmac(approval_id, sig):
        await answer_callback_query(callback_id, "Invalid signature", show_alert=True)
        return {"ok": True}

    # Look up approval
    approval = await db.get_approval(approval_id)
    if not approval:
        await answer_callback_query(
            callback_id, "Approval not found", show_alert=True
        )
        return {"ok": True}

    if approval["status"] != "pending":
        await answer_callback_query(
            callback_id, f"Already {approval['status']}", show_alert=True
        )
        return {"ok": True}

    # Check expiry
    if approval["expires_at"] < datetime.now(timezone.utc):
        await db.update_approval_status(approval_id, "expired", user_id, username)
        await answer_callback_query(
            callback_id, "Approval expired", show_alert=True
        )
        return {"ok": True}

    # Process decision
    status = "approved" if action_prefix == "a" else "denied"
    await db.update_approval_status(approval_id, status, user_id, username)

    # Answer callback (clears spinner)
    label = "Approved" if status == "approved" else "Denied"
    await answer_callback_query(callback_id, label)

    # Edit the original message to show the decision (remove buttons)
    if chat_id and message_id:
        result_html = format_approval_result(
            approval["prompt_text"], status, username
        )
        await edit_message_text(
            chat_id, message_id, result_html, parse_mode="HTML",
            reply_markup={"inline_keyboard": []},
        )

    # If approved, and there's a linked command, enqueue it for processing
    if status == "approved" and approval["command_id"]:
        from telegram_gateway.agent import process_command
        await job_queue.enqueue(approval["command_id"], process_command)
        logger.info(
            "Approval %d approved — enqueuing command %d",
            approval_id, approval["command_id"],
        )

    logger.info(
        "Approval %d %s by @%s", approval_id, status, username
    )
    return {"ok": True}


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None),
):
    """Handle incoming Telegram webhook updates."""
    # Validate webhook secret
    if x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        return Response(status_code=403)

    update = await request.json()

    # Handle inline button callback queries (approval workflow)
    callback_query = update.get("callback_query")
    if callback_query:
        return await _handle_callback_query(callback_query)

    message = update.get("message")
    if not message:
        return {"ok": True}

    user = message.get("from", {})
    user_id = user.get("id")
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    # Strip bot mentions from group messages (e.g. "@aicortexagent_bot")
    # Uses the entities array for precision, falls back to regex
    entities = message.get("entities", [])
    for ent in sorted(entities, key=lambda e: e["offset"], reverse=True):
        if ent["type"] == "mention":
            start = ent["offset"]
            end = start + ent["length"]
            text = text[:start] + text[end:]
    text = text.strip()

    if not user_id or not chat_id or not text:
        return {"ok": True}

    # Handle special commands before agent parsing
    stripped_text = text.strip()

    # Handle /flyer — generate a flyer from description (before agent parse)
    if stripped_text.startswith("/flyer"):
        # Access control check for special commands
        is_admin = not TELEGRAM_ALLOWED_USER_IDS or user_id in TELEGRAM_ALLOWED_USER_IDS
        if not is_admin:
            return {"ok": True}
        if not _check_rate_limit(user_id):
            await send_telegram_message(chat_id, "Rate limit exceeded. Please wait.")
            return {"ok": True}
        flyer_desc = stripped_text[len("/flyer"):].strip()
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{TELEGRAM_API_BASE}/sendChatAction",
                json={"chat_id": chat_id, "action": "upload_photo"},
            )
        from telegram_gateway.flyer import handle_flyer_command
        result = await handle_flyer_command(chat_id, flyer_desc)
        if "error" in result:
            await send_telegram_message(chat_id, result["error"])
        elif result.get("png"):
            caption = f"Template: {result.get('template', 'unknown')}"
            await send_telegram_photo(chat_id, result["png"], caption=caption)
            if result.get("pdf"):
                await send_telegram_document(chat_id, result["pdf"], caption="PDF version")
        else:
            await send_telegram_message(chat_id, "Flyer generated but no image produced.")
        return {"ok": True}

    # Parse command early so we can check per-agent access
    agent_type, body = _parse_command(stripped_text)

    # Access control: global allowlist OR per-agent grant
    is_global_admin = not TELEGRAM_ALLOWED_USER_IDS or user_id in TELEGRAM_ALLOWED_USER_IDS
    if not is_global_admin:
        has_agent_access = await db.check_agent_access(user_id, agent_type, chat_id)
        if not has_agent_access:
            logger.warning("Unauthorized user %d attempted [%s] access", user_id, agent_type)
            return {"ok": True}

    # Rate limit
    if not _check_rate_limit(user_id):
        await send_telegram_message(
            chat_id,
            html_module.escape("Rate limit exceeded. Please wait a moment."),
        )
        return {"ok": True}

    # Handle /new — reset conversation session
    if text.strip().startswith("/new"):
        await db.delete_session(chat_id)
        await send_telegram_message(
            chat_id,
            html_module.escape("Session reset. Next message starts a fresh conversation."),
        )
        return {"ok": True}

    # Check if agent is configured
    config = await db.get_agent_config(agent_type)
    if not config:
        await send_telegram_message(
            chat_id,
            html_module.escape(f"Agent '{agent_type}' is not available."),
        )
        return {"ok": True}

    # APM: send intro message on first interaction (no existing session)
    if agent_type == "apm":
        session = await db.get_session(chat_id)
        if not session:
            await send_telegram_message(
                chat_id,
                "<b>Hey — I'm APM, your Assistant Property Manager.</b>\n\n"
                "Here's how to work with me:\n"
                "• Prefix every message with <b>/apm</b>\n"
                "• In group chats, mention <b>@aicortexagent_bot</b>\n"
                "  Example: <code>/apm what's the status on vendor fees?</code>\n\n"
                "To personalize me to your property and workflow, run:\n"
                "<code>/apm setup</code>\n\n"
                "This takes ~5 min and makes me significantly more useful. "
                "Or just dive in — your call, boss.",
            )

    # Insert command and enqueue
    command_id = await db.insert_command(user_id, chat_id, agent_type, body)
    logger.info(
        "Command %d from user %d: [%s] %s",
        command_id, user_id, agent_type, body[:100],
    )

    # Send typing indicator
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{TELEGRAM_API_BASE}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
        )

    # Enqueue for processing
    from telegram_gateway.agent import process_command
    await job_queue.enqueue(command_id, process_command)

    return {"ok": True}
