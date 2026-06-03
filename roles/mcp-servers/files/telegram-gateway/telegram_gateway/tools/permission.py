from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from telegram_gateway import db
from telegram_gateway.bot import _generate_hmac, send_approval_request
from telegram_gateway.config import APPROVAL_TIMEOUT_MINUTES
from telegram_gateway.coder import (
    active_coder_chat, build_permission_prompt, decide_from_status,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class PermissionPromptRequest(BaseModel):
    tool_name: str = Field(..., description="Name of the tool awaiting permission")
    input: dict = Field(default_factory=dict, description="Proposed tool input")


@router.post("/permission_prompt", operation_id="permission_prompt",
             summary="Approve/deny a coder tool call via Telegram")
async def permission_prompt(req: PermissionPromptRequest) -> dict:
    """Called by the headless CLI for any non-auto-allowed tool. Blocks until
    the operator taps Approve/Deny in Telegram, then returns the CLI contract:
    {"behavior": "allow"} or {"behavior": "deny", "message": "..."}.
    """
    chat_id = active_coder_chat()
    if chat_id is None:
        return {"behavior": "deny", "message": "No active coder session."}

    prompt_text = build_permission_prompt(req.tool_name, req.input)

    # Create a pending approval NOT linked to a command_id, so the bot.py
    # callback handler records the decision but does not re-enqueue anything.
    approval_id = await db.insert_approval(
        chat_id=chat_id, prompt_text=prompt_text, hmac_token="pending",
        command_id=None, metadata={"tool": req.tool_name},
        timeout_minutes=APPROVAL_TIMEOUT_MINUTES,
    )
    hmac_token = _generate_hmac(approval_id)
    pool = await db.get_pool()
    await pool.execute("UPDATE gateway.approvals SET hmac_token=$1 WHERE id=$2",
                       hmac_token, approval_id)

    result = await send_approval_request(
        chat_id=chat_id, prompt_text=prompt_text, approval_id=approval_id,
        hmac_token=hmac_token, requested_by="coder",
    )
    if result.get("ok"):
        msg_id = result.get("result", {}).get("message_id")
        if msg_id:
            await db.update_approval_message_id(approval_id, msg_id)

    # Poll until decided or expired (the callback handler flips status).
    deadline = APPROVAL_TIMEOUT_MINUTES * 60
    waited = 0
    while waited < deadline + 5:
        row = await db.get_approval(approval_id)
        status = row["status"] if row else "denied"
        if status != "pending":
            logger.info("coder permission %s for %s", status, req.tool_name)
            return decide_from_status(status)
        await asyncio.sleep(2)
        waited += 2

    await db.update_approval_status(approval_id, "expired", 0, "system")
    return decide_from_status("expired")
