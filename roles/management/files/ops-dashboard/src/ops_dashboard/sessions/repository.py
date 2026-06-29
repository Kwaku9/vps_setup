"""Idempotent writes for real-time session ingestion."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import asyncpg

from .live_state import derive_live_state


async def _project_id(conn: asyncpg.Connection, project_path: str, source: str) -> int:
    display = project_path.rstrip("/\\").replace("\\", "/").split("/")[-1]
    return await conn.fetchval(
        """INSERT INTO sessions.projects (project_path, display_name, source)
           VALUES ($1, $2, $3)
           ON CONFLICT (project_path) DO UPDATE SET display_name = EXCLUDED.display_name
           RETURNING id""",
        project_path, display, source,
    )


async def upsert_event(conn: asyncpg.Connection, payload: dict, parsed: dict) -> dict:
    """Upsert the session, its delta messages/tool_calls, append an event,
    and update live state. Returns a compact dict for WS broadcast."""
    now = datetime.now(timezone.utc)
    source = payload.get("source", "unknown")
    project_path = payload.get("cwd") or "unknown"
    pid = await _project_id(conn, project_path, source)

    prev = await conn.fetchrow(
        "SELECT id, needs_input FROM sessions.sessions WHERE session_uuid = $1",
        parsed["session_uuid"],
    )
    prev_needs = bool(prev["needs_input"]) if prev else False
    state = derive_live_state(
        payload["event_type"],
        tool_name=payload.get("tool_name"),
        prev_needs_input=prev_needs,
    )

    session_id = await conn.fetchval(
        """INSERT INTO sessions.sessions
             (session_uuid, project_id, source, git_branch, host,
              live_status, needs_input, current_stage, last_event_at, last_event_type,
              status, started_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'active',$9)
           ON CONFLICT (session_uuid) DO UPDATE SET
             live_status     = EXCLUDED.live_status,
             needs_input     = EXCLUDED.needs_input,
             current_stage   = EXCLUDED.current_stage,
             last_event_at   = EXCLUDED.last_event_at,
             last_event_type = EXCLUDED.last_event_type,
             host            = COALESCE(EXCLUDED.host, sessions.sessions.host),
             git_branch      = COALESCE(EXCLUDED.git_branch, sessions.sessions.git_branch),
             ended_at        = CASE WHEN EXCLUDED.live_status = 'ended' THEN EXCLUDED.last_event_at
                                    ELSE sessions.sessions.ended_at END
           RETURNING id""",
        parsed["session_uuid"], pid, source, payload.get("git_branch"), payload.get("host"),
        state.live_status, state.needs_input, state.current_stage, now, payload["event_type"],
    )

    msg_id_by_uuid: dict[str, int] = {}
    for m in parsed["messages"]:
        if not m.get("uuid"):
            continue
        mid = await conn.fetchval(
            """INSERT INTO sessions.messages
                 (session_id, uuid, parent_uuid, type, role, content_text, content_json,
                  model, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
                  is_sidechain, cwd, timestamp, sequence_num)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
               ON CONFLICT (session_id, uuid) DO NOTHING
               RETURNING id""",
            session_id, m["uuid"], m["parent_uuid"], m["type"], m["role"],
            m["content_text"], json.dumps(m["content_json"]) if m["content_json"] else None,
            m["model"], m["input_tokens"], m["output_tokens"],
            m["cache_read_tokens"], m["cache_creation_tokens"],
            m["is_sidechain"], m["cwd"], m["timestamp"], m["sequence_num"],
        )
        if mid is None:  # already existed
            mid = await conn.fetchval("SELECT id FROM sessions.messages WHERE uuid = $1", m["uuid"])
        msg_id_by_uuid[m["uuid"]] = mid

    for tc in parsed["tool_calls"]:
        mid = msg_id_by_uuid.get(tc["message_uuid"])
        if mid is None:
            continue
        await conn.execute(
            """INSERT INTO sessions.tool_calls
                 (message_id, session_id, tool_use_id, tool_name, input_json,
                  result_text, status, timestamp, sequence_num)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT DO NOTHING""",
            mid, session_id, tc["tool_use_id"], tc["tool_name"],
            json.dumps(tc["input_json"]) if tc["input_json"] is not None else None,
            tc["result_text"], tc["status"], tc["timestamp"], tc["sequence_num"],
        )

    await conn.execute(
        """INSERT INTO sessions.session_events (session_id, host, event_type, payload, ts)
           VALUES ($1,$2,$3,$4,$5)""",
        session_id, payload.get("host"), payload["event_type"],
        json.dumps({k: payload.get(k) for k in ("cwd", "git_branch", "tool_name")}), now,
    )

    return {
        "session_uuid": parsed["session_uuid"],
        "live_status": state.live_status,
        "needs_input": state.needs_input,
        "current_stage": state.current_stage,
        "host": payload.get("host"),
        "last_event_at": now.isoformat(),
    }
