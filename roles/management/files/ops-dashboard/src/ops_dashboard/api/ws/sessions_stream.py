"""WebSocket fan-out + staleness sweeper for live sessions."""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class SessionsWSManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections:
            self.active_connections.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


async def staleness_sweeper(pool, ws_manager: SessionsWSManager, interval_s: float = 60.0):
    """Mark running/waiting sessions idle if no event arrived within the window."""
    stale_minutes = int(os.environ.get("SESSION_STALE_MINUTES", "10"))
    while True:
        try:
            if pool is not None:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        f"""UPDATE sessions.sessions
                              SET live_status = 'idle', current_stage = 'stale'
                            WHERE live_status IN ('running','waiting_input')
                              AND last_event_at < now() - interval '{stale_minutes} minutes'
                            RETURNING session_uuid""",
                    )
                    for r in rows:
                        await ws_manager.broadcast({
                            "type": "session_update",
                            "session_uuid": r["session_uuid"],
                            "live_status": "idle",
                        })
        except Exception:
            logger.exception("staleness sweep failed")
        await asyncio.sleep(interval_s)
