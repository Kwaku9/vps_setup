from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from telegram_gateway import db
from telegram_gateway.models import AbandonApprovalRequest, UpdateCommandStatusRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["commands"])


@router.get("/get_pending_commands", summary="Get pending commands from the queue")
async def get_pending_commands(limit: int = Query(10, ge=1, le=100)):
    """Retrieve pending commands waiting to be processed."""
    rows = await db.get_pending_commands(limit)
    return [
        {
            "id": r["id"],
            "telegram_user_id": r["telegram_user_id"],
            "telegram_chat_id": r["telegram_chat_id"],
            "agent_type": r["agent_type"],
            "message": r["message"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/get_command_history", summary="Get recent command history")
async def get_command_history(
    limit: int = Query(20, ge=1, le=100),
    agent_type: str | None = Query(None),
):
    """Retrieve recent commands with their responses."""
    rows = await db.get_command_history(limit, agent_type)
    return [
        {
            "id": r["id"],
            "telegram_user_id": r["telegram_user_id"],
            "telegram_chat_id": r["telegram_chat_id"],
            "agent_type": r["agent_type"],
            "message": r["message"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat(),
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "response_content": r["response_content"],
            "response_type": r["response_type"],
        }
        for r in rows
    ]


@router.post("/update_command_status", summary="Update a command's status")
async def update_command_status(req: UpdateCommandStatusRequest):
    """Mark a command as completed or failed, optionally inserting a response."""
    completed_at = datetime.now(timezone.utc) if req.status in ("completed", "failed") else None
    await db.update_command_status(req.command_id, req.status.value, completed_at)

    if req.response_text:
        pool = await db.get_pool()
        cmd = await pool.fetchrow(
            "SELECT telegram_chat_id, agent_type FROM gateway.commands WHERE id = $1",
            req.command_id,
        )
        if cmd:
            await db.insert_response(
                command_id=req.command_id,
                agent_type=cmd["agent_type"],
                response_type="text",
                content=req.response_text,
                chat_id=cmd["telegram_chat_id"],
            )

    return {"ok": True, "command_id": req.command_id, "status": req.status.value}


@router.get("/get_pending_approvals", summary="Get pending approval requests")
async def get_pending_approvals(limit: int = Query(10, ge=1, le=100)):
    """Retrieve pending approval requests awaiting user decision."""
    rows = await db.get_pending_approvals(limit)
    return [
        {
            "id": r["id"],
            "command_id": r["command_id"],
            "telegram_chat_id": r["telegram_chat_id"],
            "prompt_text": r["prompt_text"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat(),
            "expires_at": r["expires_at"].isoformat(),
        }
        for r in rows
    ]


@router.post("/abandon_approval", summary="Close an approval whose requester gave up")
async def abandon_approval(req: AbandonApprovalRequest):
    """Called by the PreToolUse hook when its poll window closes undecided.

    By then the hook has already fallen back to the local CLI prompt, so the
    Telegram card is dead — nobody is listening to it. Without this the row
    stays 'pending' until the TTL reaper catches it, and the card keeps live
    buttons that can't affect anything.

    Lives on the commands router (not send) so it is mounted in every BOT_MODE,
    including owui — the hook's /get_approval_status poll is here for the same
    reason.
    """
    row = await db.get_approval(req.approval_id)
    if not row:
        return {"ok": False, "error": "Approval not found"}

    if not await db.abandon_approval(req.approval_id, req.reason):
        # A decision beat us to it. Report what actually stuck.
        current = await db.get_approval(req.approval_id)
        return {
            "ok": True,
            "abandoned": False,
            "status": current["status"] if current else "unknown",
        }

    # Best-effort: strip the dead buttons off the card so a late tap can't look
    # like it did something. A Telegram failure must not fail the call — the row
    # is already closed, which is the part that matters.
    if row["telegram_message_id"]:
        try:
            from telegram_gateway.bot import edit_message_text
            from telegram_gateway.formatter import format_approval_result

            await edit_message_text(
                row["telegram_chat_id"],
                row["telegram_message_id"],
                format_approval_result(row["prompt_text"], "abandoned", "no response"),
                parse_mode="HTML",
                reply_markup={"inline_keyboard": []},
            )
        except Exception:
            logger.warning(
                "abandon_approval %d: could not update the Telegram card",
                req.approval_id, exc_info=True,
            )

    logger.info("Approval %d abandoned: %s", req.approval_id, req.reason or "-")
    return {"ok": True, "abandoned": True, "status": "abandoned"}


@router.get("/get_approval_status", summary="Check an approval's current status")
async def get_approval_status(approval_id: int = Query(..., ge=1)):
    """Check the current status of a specific approval request."""
    row = await db.get_approval(approval_id)
    if not row:
        return {"ok": False, "error": "Approval not found"}
    return {
        "ok": True,
        "id": row["id"],
        "status": row["status"],
        "command_id": row["command_id"],
        "decided_by": row.get("decided_by_username") or row["decided_by"],
        "decided_at": row["decided_at"].isoformat() if row["decided_at"] else None,
        "expires_at": row["expires_at"].isoformat(),
    }
