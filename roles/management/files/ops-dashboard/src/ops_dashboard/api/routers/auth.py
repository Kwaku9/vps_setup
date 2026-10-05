"""Sign-in, sign-out and the audit log view."""
from __future__ import annotations

import hmac
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from starlette.responses import HTMLResponse, RedirectResponse

from .. import audit
from ..auth import (config, current_user, pkce_pair, public_user, require_role, role_for, safe_next,
                    verify_cf_access, via_of)

router = APIRouter(tags=["auth"])

LOGIN_TTL = 600  # seconds a started login may take to come back from Authentik


def _page(title: str, body: str, status: int) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><body style='font:16px system-ui;max-width:32rem;margin:15vh auto;padding:0 16px'>"
        f"<h1 style='font-size:20px'>{title}</h1><p>{body}</p>"
        "<p><a href='/auth/login'>Sign in again</a></p></body>", status_code=status)


def _host(request: Request) -> str:
    return (request.headers.get("x-forwarded-host") or request.headers.get("host", "")).split(":")[0].lower()


def _start_session(request: Request, *, username: str, email: str | None, role: str, via: str) -> dict:
    now = time.time()
    request.session.clear()  # new session id on every sign-in: no fixation
    user = {"username": username, "email": email, "role": role, "via": via, "iat": now, "seen": now}
    request.session["user"] = user
    return user


@router.get("/auth/login")
async def login(request: Request, next: str = "/"):
    target = safe_next(next)
    if config.breakglass_host and _host(request) == config.breakglass_host:
        return await _breakglass_login(request, target)
    if not config.oidc_ready:
        return _page("Sign-in is not configured", "The dashboard has no Authentik client yet. "
                     "Use the break-glass address, or redeploy the management role.", 503)
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    request.session["oidc"] = {"state": state, "verifier": verifier, "next": target, "t": time.time()}
    params = {"response_type": "code", "client_id": config.client_id, "redirect_uri": config.redirect_url,
              "scope": "openid email profile groups", "state": state,
              "code_challenge": pkce_pair(verifier), "code_challenge_method": "S256"}
    return RedirectResponse(f"{config.authorize_url}?{urlencode(params)}", 302)


@router.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    pending = request.session.pop("oidc", None)
    if error or not code or not pending or not hmac.compare_digest(state, pending.get("state", "")) \
            or time.time() - pending.get("t", 0) > LOGIN_TTL:
        await audit.record(request.scope, None, action="login", outcome="failed", status=400,
                           detail={"reason": error or "state mismatch or expired"})
        return _page("Sign-in did not complete", "The sign-in expired or was interrupted.", 400)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            tok = await c.post(config.token_url, data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": config.redirect_url,
                "client_id": config.client_id, "client_secret": config.client_secret,
                "code_verifier": pending["verifier"]})
            tok.raise_for_status()
            info = await c.get(config.userinfo_url,
                               headers={"Authorization": f"Bearer {tok.json()['access_token']}"})
            info.raise_for_status()
            claims = info.json()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        await audit.record(request.scope, None, action="login", outcome="error", status=502,
                           detail={"reason": type(exc).__name__})
        return _page("Authentik did not answer", "Try again in a minute, or use the break-glass address.", 502)

    username = claims.get("preferred_username") or claims.get("email") or claims.get("sub")
    role = role_for(claims.get("groups"))
    if not role:
        await audit.record(request.scope, {"username": username}, action="login", outcome="forbidden",
                           status=403, detail={"groups": claims.get("groups") or []})
        return _page("No ops access", f"{username} is signed in to Authentik but is not in the "
                     "admins, ops-operators or ops-viewers group.", 403)
    user = _start_session(request, username=username, email=claims.get("email"), role=role,
                          via=via_of(request.headers, _host(request)))
    await audit.record(request.scope, user, action="login", detail={"method": "oidc"})
    return RedirectResponse(safe_next(pending.get("next")), 302)


async def _breakglass_login(request: Request, target: str):
    token = request.headers.get("cf-access-jwt-assertion") or request.cookies.get("CF_Authorization")
    try:
        claims = verify_cf_access(token)
    except Exception as exc:  # noqa: BLE001 — any verification failure is a refusal
        await audit.record(request.scope, None, action="login", outcome="failed", status=401,
                           detail={"method": "breakglass", "reason": type(exc).__name__})
        return _page("Break-glass sign-in refused", "No valid Cloudflare Access token came with "
                     "this request.", 401)
    email = (claims.get("email") or "").lower()
    if email not in config.breakglass_emails:
        await audit.record(request.scope, {"username": email or "unknown"}, action="login",
                           outcome="forbidden", status=403, detail={"method": "breakglass"})
        return _page("Break-glass sign-in refused", f"{email or 'This account'} is not on the "
                     "break-glass list.", 403)
    user = _start_session(request, username=email, email=email, role="admin", via="breakglass")
    await audit.record(request.scope, user, action="login", detail={"method": "breakglass"})
    return RedirectResponse(target, 302)


@router.post("/auth/logout")
async def logout(request: Request):
    user = request.session.get("user")
    if user:
        await audit.record(request.scope, user, action="logout")
    request.session.clear()
    end = config.end_session_url if user and user.get("via") != "breakglass" else ""
    return {"ok": True, "end_session_url": end or None}


@router.get("/api/me")
async def me(user: dict = Depends(current_user)):
    return public_user(user)


@router.get("/api/audit")
async def recent_audit(request: Request, limit: int = 200, user: dict = Depends(require_role("admin"))):
    pool = request.app.state.db_pool
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, ts, username, role, action, target, via, outcome, method, route, status, client_ip, detail
                 FROM sessions.ops_audit ORDER BY ts DESC LIMIT $1""", max(1, min(limit, 1000)))
    return [dict(r) for r in rows]
