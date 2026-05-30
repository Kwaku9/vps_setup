"""Read API + WebSocket for live sessions."""
from __future__ import annotations

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
                      s.input_tokens, s.output_tokens, p.display_name AS project
                 FROM sessions.sessions s
                 LEFT JOIN sessions.projects p ON p.id = s.project_id
                WHERE s.live_status IS NOT NULL AND s.live_status <> 'ended'
                ORDER BY s.needs_input DESC, s.last_event_at DESC""",
        )
    return [dict(r) for r in rows]


@router.get("/{session_uuid}/transcript")
async def transcript(session_uuid: str, since: int = 0, request: Request = None):
    pool = request.app.state.db_pool
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT m.uuid, m.role, m.type, m.content_text, m.sequence_num, m.timestamp
                 FROM sessions.messages m
                 JOIN sessions.sessions s ON s.id = m.session_id
                WHERE s.session_uuid = $1 AND m.sequence_num > $2
                ORDER BY m.sequence_num ASC LIMIT 500""",
            session_uuid, since,
        )
    return [dict(r) for r in rows]


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
