"""Append-only audit trail for the ops dashboard.

Every event is written twice: a row in sessions.ops_audit (queryable, and the
ops_dashboard role cannot UPDATE or DELETE it) and one JSON log line on the
`ops_audit` logger, which Alloy ships to Loki. A failed DB write therefore
never loses the event.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex

logger = logging.getLogger("ops_audit")

_INSERT = """INSERT INTO sessions.ops_audit
    (username, role, action, target, via, outcome, method, route, status, client_ip, user_agent, detail)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)"""


def _headers(scope) -> dict:
    return {k.decode().lower(): v.decode(errors="replace") for k, v in scope.get("headers", [])}


def client_ip(scope) -> str | None:
    h = _headers(scope)
    if h.get("cf-connecting-ip"):
        return h["cf-connecting-ip"]
    if h.get("x-forwarded-for"):
        return h["x-forwarded-for"].split(",")[0].strip()
    c = scope.get("client")
    return c[0] if c else None


def event(scope, user: dict | None, *, action: str, target: str | None = None, outcome: str = "ok",
          status: int | None = None, detail: dict | None = None) -> dict:
    from .auth import via_of  # local: auth imports this module

    h = _headers(scope)
    host = (h.get("x-forwarded-host") or h.get("host", "")).split(":")[0].lower()
    return {
        "username": (user or {}).get("username") or "anonymous",
        "role": (user or {}).get("role"),
        "action": action,
        "target": target,
        "via": (user or {}).get("via") or via_of(h, host),
        "outcome": outcome,
        "method": scope.get("method") or ("WS" if scope.get("type") == "websocket" else None),
        "route": scope.get("path"),
        "status": status,
        "client_ip": client_ip(scope),
        "user_agent": (h.get("user-agent") or "")[:300] or None,
        "detail": detail or {},
    }


async def record(scope, user: dict | None, **kw) -> dict:
    row = event(scope, user, **kw)
    logger.info(json.dumps({"audit": True, **row}, default=str, separators=(",", ":")))
    app = scope.get("app")
    pool = getattr(getattr(app, "state", None), "db_pool", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.execute(_INSERT, row["username"], row["role"], row["action"], row["target"],
                                   row["via"], row["outcome"], row["method"], row["route"], row["status"],
                                   row["client_ip"], row["user_agent"], json.dumps(row["detail"], default=str))
        except Exception as exc:  # noqa: BLE001 — the log line above already holds the event
            logger.warning("audit row not written to postgres: %s", exc)
    return row


def audit_ready(app) -> bool:
    """State-changing actions refuse to run when they could not be recorded."""
    return getattr(app.state, "db_pool", None) is not None


def notify(provider, text: str) -> None:
    """Fire-and-forget Telegram alert through the host's telegram-notify helper."""
    async def _send():
        try:
            await provider._ssh_command(f"telegram-notify {shlex.quote(text)}", timeout=15)
        except Exception as exc:  # noqa: BLE001 — an alert must never break the action
            logger.warning("telegram alert failed: %s", exc)
    asyncio.get_running_loop().create_task(_send())
