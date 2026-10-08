"""Outbound workstation bridge and authenticated, audited session replies.

The bridge can ingest and claim input only for its configured host. Browser
clients never receive its token, a socket path, or a command to execute.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from ...sessions.parser import parse_lines
from ...sessions.repository import upsert_event
from .. import audit
from ..auth import require_role
from .ingest import ws_manager

router = APIRouter(tags=["workstation-sessions"])


def bridge_host(authorization: str | None = Header(default=None)) -> str:
    supplied = (authorization or "").removeprefix("Bearer ")
    key = os.environ.get("SESSION_INGEST_TOKEN", "")
    if key and (authorization or "").startswith("Bearer "):
        for host in os.environ.get("OPS_WORKSTATION_HOSTS", "").split(","):
            host = host.strip()
            token = hmac.new(key.encode(), ("ops-workstation:v1:" + host).encode(), hashlib.sha256).hexdigest()
            if host and hmac.compare_digest(supplied, token):
                return host
    raise HTTPException(401, "invalid workstation token")


def database(request: Request):
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "sessions DB unavailable")
    return pool


class WorkstationSession(BaseModel):
    session_uuid: UUID
    agent_kind: str = Field(pattern="^(claude|codex)$")
    name: str = Field(default="", max_length=200)
    cwd: str = Field(max_length=2048)
    git_branch: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=100)
    state: str = Field(pattern="^(running|idle|waiting_input|ended)$")
    input_available: bool = False
    transcript_delta: list[str] = Field(default_factory=list, max_length=500)


class Sync(BaseModel):
    sessions: list[WorkstationSession] = Field(max_length=32)
    # A partial/failed CLI discovery must not mark previously seen sessions ended.
    discovery_complete: bool = False


@router.post("/api/workstations/sync")
async def sync(request: Request, host: str = Depends(bridge_host)):
    body = await request.body()
    if len(body) > 8 * 1024 * 1024:
        raise HTTPException(413, "workstation batch exceeds 8 MiB")
    try:
        payload = Sync.model_validate_json(body)
    except ValueError:
        raise HTTPException(422, "invalid workstation batch") from None
    pool = database(request)
    updates = []
    async with pool.acquire() as conn, conn.transaction():
        for session in payload.sessions:
            sid = str(session.session_uuid)
            parsed = parse_lines(session.transcript_delta, session.agent_kind)
            if parsed["session_uuid"] and parsed["session_uuid"] != sid:
                raise HTTPException(422, "transcript belongs to another session")
            parsed["session_uuid"] = sid
            # Serialize first ownership assignment as well as later updates.
            # Row locks alone cannot protect a UUID that has not been inserted yet.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", sid)
            previous = await conn.fetchval(
                "SELECT host FROM sessions.sessions WHERE session_uuid=$1", sid,
            )
            if previous and previous != host:
                raise HTTPException(409, "session belongs to another host")
            event = {"running": "UserPromptSubmit", "idle": "Stop",
                     "waiting_input": "Notification", "ended": "SessionEnd"}[session.state]
            result = await upsert_event(conn, {
                "session_uuid": sid, "host": host, "source": session.agent_kind,
                "cwd": session.cwd, "git_branch": session.git_branch, "event_type": event,
            }, parsed)
            await conn.execute(
                """UPDATE sessions.sessions SET live_status=$2, needs_input=$3,model=coalesce($4,model)
                   WHERE session_uuid=$1""", sid, session.state, session.state == "waiting_input", session.model,
            )
            await conn.execute(
                """INSERT INTO sessions.workstation_sessions
                       (session_id,host,name,agent_kind,input_available,last_seen)
                   SELECT id,$2,$3,$4,$5,now() FROM sessions.sessions WHERE session_uuid=$1
                   ON CONFLICT(session_id) DO UPDATE SET
                       name=EXCLUDED.name, agent_kind=EXCLUDED.agent_kind,
                       input_available=EXCLUDED.input_available, last_seen=now()""",
                sid, host, session.name, session.agent_kind,
                session.input_available and session.state != "ended",
            )
            result.update(live_status=session.state, needs_input=session.state == "waiting_input")
            updates.append(result)
        if payload.discovery_complete:
            ids = [str(s.session_uuid) for s in payload.sessions]
            await conn.execute(
                """UPDATE sessions.sessions s SET live_status='ended', needs_input=false
                   FROM sessions.workstation_sessions w
                   WHERE w.session_id=s.id AND w.host=$1 AND NOT(s.session_uuid=ANY($2::text[]))""",
                host, ids,
            )
            await conn.execute(
                """UPDATE sessions.workstation_sessions w SET input_available=false
                   FROM sessions.sessions s WHERE s.id=w.session_id AND w.host=$1
                     AND NOT(s.session_uuid=ANY($2::text[]))""", host, ids,
            )
        # Never silently repeat a dispatch after a bridge crash/ambiguous acknowledgement.
        await conn.execute(
            """UPDATE sessions.input_requests SET status='uncertain',
                   detail='Delivery acknowledgement timed out. Check the session before sending again.',
                   updated_at=now() WHERE host=$1 AND status='claimed'
                   AND claimed_at < now()-interval '5 minutes'""", host,
        )
        await conn.execute(
            """UPDATE sessions.input_requests SET status='failed',
                   detail='Session disconnected before delivery.',updated_at=now()
               WHERE host=$1 AND status='queued' AND created_at < now()-interval '5 minutes'""", host,
        )
        commands = await conn.fetch(
            """WITH pending AS (
                 SELECT r.id FROM sessions.input_requests r
                 JOIN sessions.workstation_sessions w ON w.session_id=r.session_id
                 JOIN sessions.sessions s ON s.id=r.session_id
                 WHERE r.host=$1 AND r.status='queued' AND w.input_available
                   AND w.last_seen > now()-interval '90 seconds' AND s.live_status <> 'ended'
                 ORDER BY r.created_at LIMIT 8 FOR UPDATE OF r SKIP LOCKED
               ) UPDATE sessions.input_requests r SET status='claimed',claimed_at=now(),updated_at=now()
                 FROM pending p, sessions.sessions s
                 WHERE r.id=p.id AND s.id=r.session_id
                 RETURNING r.id,s.session_uuid,r.text""", host,
        )
    for update in updates:
        await ws_manager.broadcast({"type": "session_update", **update})
    return {"ok": True, "accepted": [str(s.session_uuid) for s in payload.sessions],
            "commands": [dict(c) for c in commands]}


class Delivery(BaseModel):
    id: UUID
    status: str = Field(pattern="^(delivered|failed|uncertain)$")
    detail: str = Field(max_length=500)


@router.post("/api/workstations/result")
async def result(payload: Delivery, request: Request, host: str = Depends(bridge_host)):
    async with database(request).acquire() as conn:
        found = await conn.fetchval(
            """UPDATE sessions.input_requests SET status=$3,detail=$4,updated_at=now()
               WHERE id=$1 AND host=$2 AND status IN ('claimed','uncertain') RETURNING id""",
            payload.id, host, payload.status, payload.detail,
        )
        if not found:
            # A repeated successful receipt is safe and idempotent.
            found = await conn.fetchval(
                "SELECT id FROM sessions.input_requests WHERE id=$1 AND host=$2 AND status=$3",
                payload.id, host, payload.status,
            )
    if not found:
        raise HTTPException(404, "delivery not found")
    return {"ok": True}


class Reply(BaseModel):
    id: UUID
    text: str = Field(min_length=1, max_length=16000)

    @field_validator("text")
    @classmethod
    def valid_text(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("reply must contain text")
        return value


@router.post("/api/sessions/{session_uuid}/input", status_code=202)
async def submit_input(session_uuid: UUID, payload: Reply, request: Request,
                       user: Annotated[dict, Depends(require_role("operator"))]):
    async with database(request).acquire() as conn, conn.transaction():
        session = await conn.fetchrow(
            """SELECT s.id,w.host,w.input_available,
                      w.last_seen > now()-interval '90 seconds' AS connected
               FROM sessions.sessions s JOIN sessions.workstation_sessions w ON w.session_id=s.id
               WHERE s.session_uuid=$1 AND s.live_status <> 'ended' FOR UPDATE OF s""",
            str(session_uuid),
        )
        if not session or not session["connected"] or not session["input_available"]:
            raise HTTPException(409, "session is not connected for replies")
        existing = await conn.fetchrow("SELECT * FROM sessions.input_requests WHERE id=$1", payload.id)
        if existing:
            if existing["session_id"] != session["id"] or existing["text"] != payload.text:
                raise HTTPException(409, "reply ID was already used")
            return {"id": existing["id"], "status": existing["status"]}
        count = await conn.fetchval(
            "SELECT count(*) FROM sessions.input_requests WHERE session_id=$1 AND status IN ('queued','claimed')",
            session["id"],
        )
        if count >= 4:
            raise HTTPException(429, "wait for pending replies to be delivered")
        await conn.execute(
            """INSERT INTO sessions.input_requests(id,session_id,host,text,created_by)
               VALUES($1,$2,$3,$4,$5)""", payload.id, session["id"], session["host"],
            payload.text, user.get("username") or "operator",
        )
    await audit.record(request.scope, user, action="session-input", target=str(session_uuid), status=202,
                       detail={"request_id": str(payload.id), "characters": len(payload.text)})
    return {"id": payload.id, "status": "queued"}


@router.get("/api/sessions/{session_uuid}/input")
async def input_status(session_uuid: UUID, request: Request):
    async with database(request).acquire() as conn:
        rows = await conn.fetch(
            """SELECT r.id,r.status,r.detail,r.created_at FROM sessions.input_requests r
               JOIN sessions.sessions s ON s.id=r.session_id WHERE s.session_uuid=$1
               ORDER BY r.created_at DESC LIMIT 20""", str(session_uuid),
        )
    return [dict(r) for r in rows]
