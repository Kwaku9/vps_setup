"""Read API + WebSocket for live sessions."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from ..routers.ingest import ws_manager

router = APIRouter(prefix="/api/sessions", tags=["sessions-read"])


@router.get("/active")
async def active_sessions(request: Request):
    pool = request.app.state.db_pool
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT s.session_uuid, s.live_status, s.needs_input, s.current_stage,
                      s.host, s.git_branch, s.model, s.last_event_at,
                      s.input_tokens, s.output_tokens, p.display_name AS project,
                      a.id AS approval_id,
                      a.prompt_text AS approval_prompt,
                      a.metadata->>'tool_name' AS approval_tool,
                      (a.id IS NOT NULL) AS needs_approval
                 FROM sessions.sessions s
                 LEFT JOIN sessions.projects p ON p.id = s.project_id
                 LEFT JOIN LATERAL (
                     SELECT id, prompt_text, metadata
                       FROM gateway.approvals
                      WHERE status = 'pending' AND expires_at > now()
                        AND metadata->>'session_id' = s.session_uuid
                      ORDER BY created_at DESC LIMIT 1
                 ) a ON true
                WHERE s.live_status IS NOT NULL AND s.live_status <> 'ended'
                ORDER BY (a.id IS NOT NULL) DESC, s.needs_input DESC, s.last_event_at DESC""",
        )
    return [dict(r) for r in rows]


@router.get("/{session_uuid}/transcript")
async def transcript(session_uuid: str, since: int = 0, after_id: int | None = None, request: Request = None):
    pool = request.app.state.db_pool
    if pool is None:
        return []
    # Live hook deltas restart sequence_num at 1. Use the monotonically
    # increasing row ID for the mobile cursor so later deltas are not skipped.
    # The classic client keeps its existing `since` contract.
    cursor_column = "m.id" if after_id is not None else "m.sequence_num"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT m.id AS cursor, m.uuid, m.role, m.type, m.content_text, m.content_json,
                      m.sequence_num, m.timestamp
                 FROM sessions.messages m
                 JOIN sessions.sessions s ON s.id = m.session_id
                WHERE s.session_uuid = $1 AND {cursor_column} > $2
                  AND NOT coalesce(m.is_sidechain, false)
                ORDER BY {cursor_column} ASC LIMIT 500""",
            session_uuid, after_id if after_id is not None else since,
        )
    messages = []
    for row in rows:
        message = dict(row)
        # asyncpg returns JSONB as a string unless a custom codec is registered.
        # Keep this additive field a JSON value for both dashboard clients.
        content = message.get("content_json")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (ValueError, TypeError):
                content = None
        message["content_json"] = content
        messages.append(message)
    return messages


@router.get("/{session_uuid}")
async def session_detail(session_uuid: str, request: Request):
    pool = request.app.state.db_pool
    if pool is None:
        return {}
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT s.*, p.display_name AS project
                 FROM sessions.sessions s
                 LEFT JOIN sessions.projects p ON p.id = s.project_id
                WHERE s.session_uuid = $1""",
            session_uuid,
        )
    return dict(row) if row else {}


@router.websocket("/ws")
async def sessions_ws(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
