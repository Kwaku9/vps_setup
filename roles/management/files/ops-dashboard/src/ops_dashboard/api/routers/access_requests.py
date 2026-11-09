"""Request desk: anyone signed in asks for more access, an admin approves or denies.

Two audiences, two ways in:

  portal.<domain>/request   Requesters (free, paid, students). Traefik routes the
                            path here. No dashboard session: every call carries
                            the Cloudflare Access token of the path-scoped app
                            (cloudflare_access.request_desk), verified against
                            Cloudflare's keys and CF_ACCESS_REQUEST_AUD. The plain
                            email header is never trusted. AuthMiddleware exempts
                            /request for exactly this reason.
  /api/access-requests      Admins, in the ops dashboard (Students page). Approving
                            "students" or "paid_users" joins that Authentik group
                            through the svc-ops-students token; "other" is recorded
                            and the owner acts by hand.

New requests and decisions are audited and sent to Telegram.
"""
from __future__ import annotations

import os
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from .. import audit
from ..auth import _same_origin, config, require_role
from ..dependencies import DashboardState, get_state
from . import students as authentik

router = APIRouter(tags=["access-requests"])

KINDS = {
    "students": "Join the students group (student apps, Grafana Students org, local model)",
    "paid_users": "Paid models in Open WebUI",
    "other": "Something else",
}
GROUP_KINDS = {"students", "paid_users"}
MAX_PER_DAY = 5
PAGE = Path(__file__).resolve().parent.parent / "request_page.html"

_jwk_client = None


def _verify(request: Request) -> str:
    """Email of the caller from the request-desk Access token, else 401."""
    global _jwk_client
    import jwt  # PyJWT, as in auth.verify_cf_access

    # /request is outside AuthMiddleware, so its CSRF backstop is repeated here:
    # Cloudflare adds the token from a cookie, which a cross-site POST would carry.
    if request.method not in ("GET", "HEAD") and not _same_origin(request.scope):
        raise HTTPException(403, "cross-origin request refused")

    aud = os.environ.get("CF_ACCESS_REQUEST_AUD", "")
    token = request.headers.get("cf-access-jwt-assertion")
    if not token or not aud or not config.cf_team_domain:
        raise HTTPException(401, "Sign in through portal first.")
    try:
        if _jwk_client is None:
            _jwk_client = jwt.PyJWKClient(f"https://{config.cf_team_domain}/cdn-cgi/access/certs",
                                          cache_keys=True, lifespan=3600)
        key = _jwk_client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=aud,
                            issuer=f"https://{config.cf_team_domain}")
    except Exception:  # noqa: BLE001 — any verification failure is the same answer
        raise HTTPException(401, "Your sign-in could not be verified. Reload the page.") from None
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(401, "Your sign-in carries no email address.")
    return email


def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "The request desk is offline (no database). Try again later.")
    return pool


async def _account(email: str) -> dict | None:
    """The Authentik account for this email, or None."""
    async with authentik._client() as c:
        # Post-filtered below: Authentik ignores some list filters (see memory
        # authentik-api-name-filters-ignored), so never trust the filter alone.
        r = await c.get("/core/users/", params={"email": email, "search": email, "page_size": 100})
        r.raise_for_status()
        hits = [u for u in r.json().get("results", []) if (u.get("email") or "").lower() == email]
    return authentik._person(hits[0]) if hits else None


def _row(r) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}


# ── requester side ──────────────────────────────────────────────────────────

@router.get("/request", include_in_schema=False)
async def request_page_redirect():
    return RedirectResponse("/request/", 307)


@router.get("/request/", include_in_schema=False)
async def request_page():
    return FileResponse(PAGE, media_type="text/html", headers={"Cache-Control": "no-store"})


@router.get("/request/api/me")
async def my_requests(request: Request):
    email = _verify(request)
    person = await _account(email)
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, created_at, kind, reason, status, decided_at, note FROM sessions.access_requests "
            "WHERE email = $1 ORDER BY created_at DESC LIMIT 50", email)
    groups = person["groups"] if person else []
    return {
        "email": email,
        "name": (person or {}).get("name") or "",
        "groups": groups,
        "kinds": [{"kind": k, "label": v, "have": k in groups} for k, v in KINDS.items()],
        "requests": [_row(r) for r in rows],
    }


class NewRequest(BaseModel):
    kind: str
    reason: str = Field(min_length=10, max_length=1000)


@router.post("/request/api/requests")
async def create_request(body: NewRequest, request: Request):
    email = _verify(request)
    if body.kind not in KINDS:
        raise HTTPException(422, "Pick one of the listed kinds of access.")
    person = await _account(email)
    if person is None:
        raise HTTPException(409, "No account matches your sign-in email. Sign up at auth first.")
    if body.kind in GROUP_KINDS and body.kind in person["groups"]:
        raise HTTPException(409, "You already have that access.")
    who = {"username": email, "role": None, "via": "request-desk"}
    async with _pool(request).acquire() as conn:
        recent = await conn.fetchval(
            "SELECT count(*) FROM sessions.access_requests WHERE email = $1 AND created_at > now() - interval '1 day'",
            email)
        if recent >= MAX_PER_DAY:
            raise HTTPException(429, f"That is {MAX_PER_DAY} requests today. Try again tomorrow.")
        try:
            rid = await conn.fetchval(
                "INSERT INTO sessions.access_requests (email, username, kind, reason) VALUES ($1, $2, $3, $4) RETURNING id",
                email, person["username"], body.kind, body.reason.strip())
        except Exception as exc:  # unique index: one open request per kind
            if "access_requests_one_open" in str(exc):
                raise HTTPException(409, "You already have an open request for that. It is waiting for review.") from None
            raise
    await audit.record(request.scope, who, action="access-request", target=str(rid),
                       status=200, detail={"kind": body.kind})
    audit.notify(get_state().vps_provider,
                 f"🙋 <b>access request</b> #{rid} from {escape(email)}: <b>{escape(body.kind)}</b>\n"
                 f"{escape(body.reason.strip()[:300])}\nDecide in ops, Students page.")
    return {"ok": True, "id": rid}


@router.post("/request/api/requests/{rid}/withdraw")
async def withdraw_request(rid: int, request: Request):
    email = _verify(request)
    async with _pool(request).acquire() as conn:
        done = await conn.fetchval(
            "UPDATE sessions.access_requests SET status = 'withdrawn', decided_at = now(), decided_by = $2 "
            "WHERE id = $1 AND email = $2 AND status = 'pending' RETURNING id", rid, email)
    if not done:
        raise HTTPException(404, "No open request of yours with that number.")
    await audit.record(request.scope, {"username": email, "role": None, "via": "request-desk"},
                       action="access-request-withdraw", target=str(rid), status=200)
    return {"ok": True}


# ── admin side ──────────────────────────────────────────────────────────────

@router.get("/api/access-requests")
async def list_requests(request: Request, _: dict = Depends(require_role("admin"))):
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM sessions.access_requests "
            "ORDER BY (status = 'pending') DESC, created_at DESC LIMIT 200")
    return {"requests": [_row(r) for r in rows], "kinds": KINDS}


class Decision(BaseModel):
    decision: str
    note: str = Field(default="", max_length=1000)


@router.post("/api/access-requests/{rid}/decide")
async def decide_request(rid: int, body: Decision, request: Request,
                         user: dict = Depends(require_role("admin")),
                         state: DashboardState = Depends(get_state)):
    if body.decision not in ("approve", "deny"):
        raise HTTPException(422, "decision must be approve or deny")
    pool = _pool(request)
    async with pool.acquire() as conn:
        req = await conn.fetchrow("SELECT * FROM sessions.access_requests WHERE id = $1", rid)
    if req is None:
        raise HTTPException(404, "No such request.")
    if req["status"] != "pending":
        raise HTTPException(409, f"That request is already {req['status']}.")

    granted = None
    if body.decision == "approve" and req["kind"] in GROUP_KINDS:
        person = await _account(req["email"])
        if person is None:
            raise HTTPException(409, "Their account is gone from Authentik; deny it instead.")
        if not person["active"]:
            raise HTTPException(409, "Their account is inactive (email not verified); it cannot join a group yet.")
        async with authentik._client() as c:
            gpk = await authentik._group_pk(c, req["kind"])
            r = await c.post(f"/core/groups/{gpk}/add_user/", json={"pk": person["pk"]})
        if r.status_code not in (200, 204):
            await audit.record(request.scope, user, action="access-request-approve", target=str(rid),
                               outcome="error", status=502, detail={"authentik_status": r.status_code})
            raise HTTPException(502, f"Authentik refused the change (HTTP {r.status_code}). Nothing was recorded.")
        granted = req["kind"]

    status = "approved" if body.decision == "approve" else "denied"
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions.access_requests SET status = $2, decided_at = now(), decided_by = $3, note = $4 "
            "WHERE id = $1 AND status = 'pending'", rid, status, user["username"], body.note.strip() or None)
    await audit.record(request.scope, user, action=f"access-request-{body.decision}", target=str(rid),
                       status=200, detail={"email": req["email"], "kind": req["kind"], "granted_group": granted})
    audit.notify(state.vps_provider,
                 f"{'✅' if status == 'approved' else '⛔'} <b>access request</b> #{rid} {status} by "
                 f"{escape(user['username'])}: {escape(req['email'])} {escape(req['kind'])}"
                 + (f" (joined {escape(granted)})" if granted else ""))
    return {"ok": True, "id": rid, "status": status, "granted_group": granted}
