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

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from telegram_gateway import db, owui_runner, sessions
from telegram_gateway.config import (
    AUTH_TOKEN, MCP_SERVER_PORT, OWUI_APPROVAL_TIMEOUT_MINUTES,
    OWUI_AUTO_ALLOW_TOOLS,
    HISTORIAN_MCP_CONFIG, HISTORIAN_AUTO_ALLOW_TOOLS, HISTORIAN_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["owui"])

# Process-unique, monotonically increasing run id used to correlate a streamed
# turn with the approvals its PreToolUse hook raises (passed to the hook as
# TELEGRAM_CHAT_ID, echoed back on /request_approval).
_run_counter = int(time.time() * 1000)


def _next_run_id() -> int:
    global _run_counter
    _run_counter += 1
    return _run_counter


class BindRequest(BaseModel):
    owui_chat_id: str
    workspace: str
    session_id: str | None = None


class StreamRequest(BaseModel):
    owui_chat_id: str
    prompt: str
    workspace: str | None = None  # used only when the chat has no binding yet
    persona: str | None = None    # "historian" selects the recall-tools persona


class ApprovalDecision(BaseModel):
    approval_id: int
    decision: Literal["approved", "denied"]


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


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _merge(turn: AsyncIterator, queue: asyncio.Queue) -> AsyncIterator[tuple]:
    """Interleave the CLI turn feed with approval events, whichever is ready.

    Yields ``("approval", dict)`` for hook-raised approvals and
    ``("item", (FeedItem, code))`` for CLI feed items, until the turn ends.
    """
    turn_task: asyncio.Future | None = asyncio.ensure_future(turn.__anext__())
    q_task: asyncio.Future = asyncio.ensure_future(queue.get())
    try:
        while turn_task is not None:
            done, _ = await asyncio.wait(
                {t for t in (turn_task, q_task) if t is not None},
                return_when=asyncio.FIRST_COMPLETED)
            if q_task in done:
                yield ("approval", q_task.result())
                q_task = asyncio.ensure_future(queue.get())
            if turn_task in done:
                try:
                    yield ("item", turn_task.result())
                    turn_task = asyncio.ensure_future(turn.__anext__())
                except StopAsyncIteration:
                    turn_task = None
    finally:
        q_task.cancel()
        if turn_task is not None:
            turn_task.cancel()


@router.post("/coder/stream", summary="Resume a Claude Code session, stream SSE")
async def coder_stream(req: StreamRequest):
    binding = await db.get_owui_binding(req.owui_chat_id)
    workspace = binding["workspace"] if binding else req.workspace
    session_id = binding["session_id"] if binding else None
    if not workspace:
        return Response(status_code=409, content="chat is not bound to a workspace")

    run_id = _next_run_id()
    queue = owui_runner.register_run(run_id)
    # Point the inherited PreToolUse hook at THIS service with the run id as its
    # chat id, so /request_approval correlates back to this stream.
    env = {
        "TELEGRAM_GATEWAY_URL": f"http://127.0.0.1:{MCP_SERVER_PORT}",
        "TELEGRAM_GATEWAY_TOKEN": AUTH_TOKEN,
        "TELEGRAM_CHAT_ID": str(run_id),
        "TELEGRAM_APPROVAL_FAIL_CLOSED": "1",
        "TELEGRAM_APPROVAL_AUTO_ALLOW": OWUI_AUTO_ALLOW_TOOLS,
    }

    async def gen() -> AsyncIterator[str]:
        lock = owui_runner.workspace_lock(workspace)
        async with lock:
            try:
                if req.persona == "historian":
                    turn = owui_runner.run_coder_turn(
                        req.prompt, workspace, session_id,
                        env_overrides=env, allowed_tools=HISTORIAN_AUTO_ALLOW_TOOLS,
                        mcp_config=HISTORIAN_MCP_CONFIG,
                        append_system_prompt=HISTORIAN_SYSTEM_PROMPT)
                else:
                    turn = owui_runner.run_coder_turn(
                        req.prompt, workspace, session_id,
                        env_overrides=env, allowed_tools=OWUI_AUTO_ALLOW_TOOLS)
                async for kind, payload in _merge(turn, queue):
                    if kind == "approval":
                        yield _sse("approval", payload)
                        continue
                    item, code = payload
                    if item.kind == "session" and item.text:
                        await db.upsert_owui_binding(
                            req.owui_chat_id, workspace, item.text)
                        yield _sse("session", {"session_id": item.text})
                    elif item.kind == "_exit":
                        if code not in (0, None) and "No conversation found" in item.text:
                            # stale transcript: drop the binding so the next
                            # message starts a fresh session
                            await db.upsert_owui_binding(
                                req.owui_chat_id, workspace, None)
                        yield _sse("done", {"exit_code": code,
                                            "stderr": item.text if code else ""})
                    else:
                        yield _sse(item.kind, {"text": item.text,
                                               "detail": item.detail})
            finally:
                owui_runner.unregister_run(run_id)

    return StreamingResponse(gen(), media_type="text/event-stream")
