"""OpenWebUI-facing HTTP API for resuming VPS Claude Code sessions.

Mounted only when ``BOT_MODE == "owui"``. Endpoints:
- ``GET  /coder/sessions``   — list workspaces, or recent sessions in a workspace
- ``GET  /coder/binding``    — what session an OpenWebUI chat is bound to
- ``POST /coder/bind``       — bind an OpenWebUI chat to a session (or clear → /new)
- ``POST /coder/stream``     — run one resumed turn, streamed as SSE (see Task 6)
- ``POST /coder/approve``    — record a tool-approval decision from OpenWebUI
- ``POST /request_approval`` — Telegram-free intake for the PreToolUse hook

The hook (running inside the OWUI-launched ``claude``) is pointed at this service
with a per-run synthetic ``chat_id``; ``/request_approval`` inserts a pending
``gateway.approvals`` row and hands it to the running stream via the in-process
approval registry, which surfaces it as a native OpenWebUI confirmation.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from telegram_gateway import db, owui_runner, sessions
from telegram_gateway.config import OWUI_APPROVAL_TIMEOUT_MINUTES

logger = logging.getLogger(__name__)

router = APIRouter(tags=["owui"])


class BindRequest(BaseModel):
    owui_chat_id: str
    workspace: str
    session_id: str | None = None


class ApprovalDecision(BaseModel):
    approval_id: int
    decision: str  # "approved" | "denied"


class RequestApproval(BaseModel):
    chat_id: int
    prompt_text: str
    metadata: dict | None = None


@router.get("/coder/sessions", summary="List resumable Claude Code sessions")
async def coder_sessions(workspaces_only: bool = False,
                         workspace: str | None = None):
    if workspaces_only:
        return {"workspaces": sessions.list_workspaces()}
    return {
        "workspace": workspace,
        "sessions": [asdict(s) for s in sessions.list_sessions(workspace=workspace)],
    }


@router.get("/coder/binding", summary="Session bound to an OpenWebUI chat")
async def coder_binding(owui_chat_id: str = Query(...)):
    row = await db.get_owui_binding(owui_chat_id)
    if not row:
        return {"bound": False}
    return {"bound": True, "workspace": row["workspace"],
            "session_id": row["session_id"]}


@router.post("/coder/bind", summary="Bind an OpenWebUI chat to a session")
async def coder_bind(req: BindRequest):
    await db.upsert_owui_binding(req.owui_chat_id, req.workspace, req.session_id)
    return {"ok": True}


@router.post("/coder/approve", status_code=204,
             summary="Record a tool-approval decision from OpenWebUI")
async def coder_approve(req: ApprovalDecision):
    await db.update_approval_status(req.approval_id, req.decision,
                                    decided_by=0, decided_by_username="owui")
    return Response(status_code=204)


@router.post("/request_approval", summary="PreToolUse hook intake (no Telegram)")
async def request_approval(req: RequestApproval):
    meta = req.metadata or {}
    approval_id = await db.insert_approval(
        chat_id=req.chat_id, prompt_text=req.prompt_text, hmac_token="owui",
        metadata=meta, timeout_minutes=OWUI_APPROVAL_TIMEOUT_MINUTES)
    owui_runner.push_approval(req.chat_id, {
        "approval_id": approval_id,
        "tool": meta.get("tool_name"),
        "summary": req.prompt_text,
    })
    return {"ok": True, "approval_id": approval_id}
