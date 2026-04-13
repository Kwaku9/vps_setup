from __future__ import annotations

import logging
import os
import tempfile

import httpx
from fastapi import APIRouter

from telegram_gateway.bot import (
    _generate_hmac,
    send_approval_request,
    send_telegram_message,
    send_telegram_audio,
    send_telegram_video,
    send_telegram_voice,
    send_telegram_document,
    send_telegram_photo,
)
from telegram_gateway.config import (
    APPROVAL_TIMEOUT_MINUTES,
    GRAFANA_URL,
    GRAFANA_USER,
    GRAFANA_PASSWORD,
)
from telegram_gateway import db
from telegram_gateway.formatter import (
    escape_markdown,
    format_code_block,
    format_notification,
    format_stderr,
)
from telegram_gateway.models import (
    ApprovalResponse,
    GrafanaScreenshotRequest,
    SendApprovalRequest,
    SendAudioRequest,
    SendCodeRequest,
    SendDocumentRequest,
    SendMessageRequest,
    SendNotificationRequest,
    SendResponse,
    SendStderrRequest,
    SendVideoRequest,
    SendVoiceRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["send"])


@router.post("/send_message", summary="Send a text message to a Telegram chat")
async def send_message(req: SendMessageRequest) -> SendResponse:
    """Send a plain text or formatted message to a Telegram chat."""
    text = req.text
    parse_mode = req.parse_mode
    if parse_mode == "MarkdownV2":
        text = escape_markdown(text)
    result = await send_telegram_message(req.chat_id, text, parse_mode)
    if result.get("ok"):
        return SendResponse(
            ok=True,
            message_id=result.get("result", {}).get("message_id"),
        )
    return SendResponse(ok=False, error=str(result))


@router.post("/send_code", summary="Send a code block to a Telegram chat")
async def send_code(req: SendCodeRequest) -> SendResponse:
    """Send a formatted code block to a Telegram chat."""
    text = format_code_block(req.code, req.language)
    result = await send_telegram_message(req.chat_id, text)
    if result.get("ok"):
        return SendResponse(
            ok=True,
            message_id=result.get("result", {}).get("message_id"),
        )
    return SendResponse(ok=False, error=str(result))


@router.post("/send_notification", summary="Send a notification to a Telegram chat")
async def send_notification(req: SendNotificationRequest) -> SendResponse:
    """Send a bold-titled notification to a Telegram chat."""
    text = format_notification(req.title, req.body)
    result = await send_telegram_message(req.chat_id, text)
    if result.get("ok"):
        return SendResponse(
            ok=True,
            message_id=result.get("result", {}).get("message_id"),
        )
    return SendResponse(ok=False, error=str(result))


@router.post("/send_audio", summary="Send an audio file to a Telegram chat")
async def send_audio(req: SendAudioRequest) -> SendResponse:
    """Send an audio file (music/podcast) to a Telegram chat.

    The audio URL can be an HTTP/HTTPS link (Telegram downloads it server-side)
    or a Telegram file_id from a previously uploaded file.
    Shows a music player UI in the chat.
    """
    result = await send_telegram_audio(
        chat_id=req.chat_id,
        audio=req.audio,
        caption=req.caption,
        title=req.title,
        performer=req.performer,
    )
    if result.get("ok"):
        return SendResponse(
            ok=True,
            message_id=result.get("result", {}).get("message_id"),
        )
    return SendResponse(ok=False, error=str(result))


@router.post("/send_video", summary="Send a video file to a Telegram chat")
async def send_video(req: SendVideoRequest) -> SendResponse:
    """Send a video file to a Telegram chat.

    The video URL can be an HTTP/HTTPS link or a Telegram file_id.
    Shows an inline video player in the chat.
    """
    result = await send_telegram_video(
        chat_id=req.chat_id,
        video=req.video,
        caption=req.caption,
    )
    if result.get("ok"):
        return SendResponse(
            ok=True,
            message_id=result.get("result", {}).get("message_id"),
        )
    return SendResponse(ok=False, error=str(result))


@router.post("/send_voice", summary="Send a voice message to a Telegram chat")
async def send_voice(req: SendVoiceRequest) -> SendResponse:
    """Send a voice message to a Telegram chat.

    The voice URL should be an .ogg file encoded with OPUS, or a Telegram file_id.
    Shows a waveform UI in the chat (like a voice note).
    Ideal for TTS-generated audio responses.
    """
    result = await send_telegram_voice(
        chat_id=req.chat_id,
        voice=req.voice,
        caption=req.caption,
    )
    if result.get("ok"):
        return SendResponse(
            ok=True,
            message_id=result.get("result", {}).get("message_id"),
        )
    return SendResponse(ok=False, error=str(result))


@router.post("/send_document", summary="Send a document/file to a Telegram chat")
async def send_document(req: SendDocumentRequest) -> SendResponse:
    """Send a generic document/file to a Telegram chat.

    The document URL can be an HTTP/HTTPS link or a Telegram file_id.
    Shows as a downloadable file in the chat.
    """
    result = await send_telegram_document(
        chat_id=req.chat_id,
        document=req.document,
        caption=req.caption,
    )
    if result.get("ok"):
        return SendResponse(
            ok=True,
            message_id=result.get("result", {}).get("message_id"),
        )
    return SendResponse(ok=False, error=str(result))


@router.post("/send_stderr", summary="Send stderr output to a Telegram chat")
async def send_stderr(req: SendStderrRequest) -> SendResponse:
    """Send stderr output with terminal-style formatting (HTML pre block).

    Useful for forwarding CLI errors, warnings, and diagnostic output
    to the user on Telegram with monospace formatting.
    """
    text = format_stderr(req.stderr_text)
    result = await send_telegram_message(req.chat_id, text, parse_mode="HTML")
    if result.get("ok"):
        msg_id = result.get("result", {}).get("message_id")
        # Optionally store as a response in the DB
        if req.command_id:
            await db.insert_response(
                command_id=req.command_id,
                agent_type="system",
                response_type="stderr",
                content=req.stderr_text,
                chat_id=req.chat_id,
                payload={"source": "mcp_tool"},
            )
        return SendResponse(ok=True, message_id=msg_id)
    return SendResponse(ok=False, error=str(result))


@router.post(
    "/request_approval",
    summary="Send an approval request with Approve/Deny buttons",
)
async def request_approval(req: SendApprovalRequest) -> ApprovalResponse:
    """Send an approval request to a Telegram chat with inline buttons.

    Creates a pending approval record and sends a message with
    Approve/Deny buttons. The user taps a button to approve or deny.
    If approved and a command_id is linked, the command is automatically
    enqueued for processing.

    Returns the approval_id for status tracking.
    """
    # Create HMAC token (generated after insert so we have the ID)
    # Two-step: insert first with placeholder, then update
    placeholder_hmac = "pending"
    approval_id = await db.insert_approval(
        chat_id=req.chat_id,
        prompt_text=req.prompt_text,
        hmac_token=placeholder_hmac,
        command_id=req.command_id,
        metadata=req.metadata,
        timeout_minutes=APPROVAL_TIMEOUT_MINUTES,
    )

    # Generate real HMAC from the approval ID
    hmac_token = _generate_hmac(approval_id)
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE gateway.approvals SET hmac_token = $1 WHERE id = $2",
        hmac_token, approval_id,
    )

    # Send the approval message with buttons
    result = await send_approval_request(
        chat_id=req.chat_id,
        prompt_text=req.prompt_text,
        approval_id=approval_id,
        hmac_token=hmac_token,
        requested_by=req.requested_by,
    )

    if result.get("ok"):
        # Store the message_id so we can edit it after decision
        msg_id = result.get("result", {}).get("message_id")
        if msg_id:
            await db.update_approval_message_id(approval_id, msg_id)
        return ApprovalResponse(
            ok=True, approval_id=approval_id, status="pending"
        )
    return ApprovalResponse(ok=False, error=str(result))


@router.post("/grafana_screenshot", summary="Capture and send a Grafana dashboard screenshot")
async def grafana_screenshot(req: GrafanaScreenshotRequest) -> SendResponse:
    """Fetch a Grafana dashboard or panel as a PNG and send it to Telegram.

    Uses the Grafana Image Renderer sidecar. Specify dashboard_uid to capture
    the full dashboard, or add panel_id for a single panel.
    """
    render_timeout = req.render_timeout
    if req.panel_id is not None:
        path = f"/render/d-solo/{req.dashboard_uid}/"
        params = f"orgId=1&panelId={req.panel_id}&from={req.from_time}&to={req.to_time}&width={req.width}&height={req.height}&timeout={render_timeout}"
    else:
        path = f"/render/d/{req.dashboard_uid}/"
        params = f"orgId=1&from={req.from_time}&to={req.to_time}&width={req.width}&height={req.height}&timeout={render_timeout}&kiosk"

    render_url = f"{GRAFANA_URL}{path}?{params}"

    tmp_path = None
    try:
        async with httpx.AsyncClient(
            auth=(GRAFANA_USER, GRAFANA_PASSWORD),
            timeout=render_timeout + 15,
            follow_redirects=True,
        ) as client:
            resp = await client.get(render_url)

        if resp.status_code != 200:
            return SendResponse(ok=False, error=f"Grafana render failed: HTTP {resp.status_code}")

        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type:
            return SendResponse(ok=False, error=f"Unexpected content-type: {content_type}")

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name

        caption = req.caption or f"Dashboard: {req.dashboard_uid} ({req.from_time} → {req.to_time})"
        result = await send_telegram_photo(req.chat_id, tmp_path, caption=caption)

        if result.get("ok"):
            return SendResponse(ok=True, message_id=result.get("result", {}).get("message_id"))
        return SendResponse(ok=False, error=str(result))

    except Exception as e:
        logger.exception("grafana_screenshot failed")
        return SendResponse(ok=False, error=str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


