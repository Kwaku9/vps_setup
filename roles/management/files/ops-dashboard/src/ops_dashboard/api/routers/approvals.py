"""Approval queue: list pending gateway approvals and record decisions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..routers.ingest import ws_manager

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

# dashboard decision verb -> gateway.approvals.status value
_DECISIONS = {"approve": "approved", "deny": "denied"}


async def apply_decision(conn, approval_id: int, decision: str) -> bool:
    """Race-safe status flip. Returns True iff exactly one pending row was updated."""
    status = _DECISIONS[decision]
    res = await conn.execute(
        """UPDATE gateway.approvals
              SET status = $2, decided_at = now(), decided_by_username = 'dashboard'
            WHERE id = $1 AND status = 'pending'""",
        approval_id, status,
    )
    return str(res).strip().endswith("1")


@router.get("/pending")
async def pending(request: Request):
    pool = request.app.state.db_pool
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, prompt_text, metadata, created_at, expires_at
                 FROM gateway.approvals
                WHERE status = 'pending' AND expires_at > now()
                ORDER BY created_at ASC""",
        )
    return [dict(r) for r in rows]


@router.post("/{approval_id}/decide")
async def decide(approval_id: int, request: Request):
    body = await request.json()
    decision = body.get("decision")
    if decision not in _DECISIONS:
        raise HTTPException(status_code=422, detail="decision must be 'approve' or 'deny'")
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        ok = await apply_decision(conn, approval_id, decision)
    if not ok:
        raise HTTPException(status_code=409, detail="approval already decided, expired, or not found")
    await ws_manager.broadcast({
        "type": "approval_decided",
        "approval_id": approval_id,
        "status": _DECISIONS[decision],
    })
    return {"ok": True, "id": approval_id, "status": _DECISIONS[decision]}
