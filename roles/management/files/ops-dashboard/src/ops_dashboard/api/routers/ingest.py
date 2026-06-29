"""Real-time session ingest endpoint."""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException, Request

from ...sessions.parser import parse_lines
from ...sessions.repository import upsert_event
from ..ws.sessions_stream import SessionsWSManager

router = APIRouter(prefix="/api/sessions", tags=["sessions-ingest"])

# Shared manager — also imported by the read router and main.py lifespan.
ws_manager = SessionsWSManager()


def _check_token(authorization: str | None):
    expected = os.environ.get("SESSION_INGEST_TOKEN", "")
    if not expected or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="invalid ingest token")


async def handle_ingest(pool, payload: dict) -> dict:
    parsed = parse_lines(payload.get("transcript_delta", []), payload.get("source", "unknown"))
    # Hooks always send session_uuid even when the delta is empty.
    parsed["session_uuid"] = parsed["session_uuid"] or payload["session_uuid"]
    if pool is None:
        # Pool never initialised (startup DB failure). Fail loudly instead of
        # 200-ing while silently dropping the event.
        raise HTTPException(status_code=503, detail="sessions DB unavailable")
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await upsert_event(conn, payload, parsed)


@router.post("/ingest")
async def ingest_event(request: Request, authorization: str | None = Header(default=None)):
    _check_token(authorization)
    payload = await request.json()
    if "session_uuid" not in payload or "event_type" not in payload:
        raise HTTPException(status_code=422, detail="session_uuid and event_type required")
    result = await handle_ingest(request.app.state.db_pool, payload)
    await ws_manager.broadcast({"type": "session_update", **result})
    return {"ok": True, **result}
