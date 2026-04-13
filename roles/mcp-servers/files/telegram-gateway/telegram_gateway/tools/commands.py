from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from telegram_gateway import db
from telegram_gateway.models import UpdateCommandStatusRequest

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
