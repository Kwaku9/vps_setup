"""Who is calling the dashboard, and what they may do.

Two ways in, one session cookie:

  ops.<domain>         Authentik OIDC (authorization code + PKCE). The role comes
                       from the user's Authentik groups.
  breakglass.<domain>  Cloudflare Access email OTP, for when Authentik is down.
                       The signed Cf-Access-Jwt-Assertion is verified against
                       Cloudflare's keys and this app's audience tag. The plain
                       Cf-Access-Authenticated-User-Email header is never trusted:
                       any container on the flat network can reach this app
                       directly and forge it. The email must also be on
                       OPS_BREAKGLASS_EMAILS. Break-glass sessions are admin.

AuthMiddleware enforces a session on every path except the token-authed machine
endpoints in EXEMPT, so a new router cannot forget to. Per-route roles are
checked by require_role().
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from starlette.responses import JSONResponse, RedirectResponse

from . import audit

# Highest matching group wins. A user with none of these groups gets no role
# and is refused at login.
ROLE_GROUPS = [("admin", "admins"), ("operator", "ops-operators"), ("viewer", "ops-viewers")]
RANK = {"viewer": 1, "operator": 2, "admin": 3}

# Machine endpoints with their own bearer token, plus the login flow itself.
EXEMPT_PREFIXES = ("/auth/",)
EXEMPT_PATHS = {"/api/health", "/api/sessions/ingest", "/api/repo-radar/ingest", "/favicon.ico"}


def _env_list(name: str) -> set[str]:
    return {x.strip().lower() for x in os.environ.get(name, "").split(",") if x.strip()}


@dataclass
class AuthConfig:
    session_secret: str = field(default_factory=lambda: os.environ.get("OPS_SESSION_SECRET", ""))
    client_id: str = field(default_factory=lambda: os.environ.get("OIDC_CLIENT_ID", ""))
    client_secret: str = field(default_factory=lambda: os.environ.get("OIDC_CLIENT_SECRET", ""))
    authorize_url: str = field(default_factory=lambda: os.environ.get("OIDC_AUTHORIZE_URL", ""))
    token_url: str = field(default_factory=lambda: os.environ.get("OIDC_TOKEN_URL", ""))
    userinfo_url: str = field(default_factory=lambda: os.environ.get("OIDC_USERINFO_URL", ""))
    redirect_url: str = field(default_factory=lambda: os.environ.get("OIDC_REDIRECT_URL", ""))
    end_session_url: str = field(default_factory=lambda: os.environ.get("OIDC_END_SESSION_URL", ""))
    breakglass_host: str = field(default_factory=lambda: os.environ.get("OPS_BREAKGLASS_HOST", "").lower())
    cf_team_domain: str = field(default_factory=lambda: os.environ.get("CF_ACCESS_TEAM_DOMAIN", ""))
    cf_breakglass_aud: str = field(default_factory=lambda: os.environ.get("CF_ACCESS_BREAKGLASS_AUD", ""))
    breakglass_emails: set[str] = field(default_factory=lambda: _env_list("OPS_BREAKGLASS_EMAILS"))

    @property
    def oidc_ready(self) -> bool:
        return all([self.client_id, self.client_secret, self.authorize_url, self.token_url,
                    self.userinfo_url, self.redirect_url])


config = AuthConfig()


def role_for(groups) -> str | None:
    names = set(groups or [])
    for role, group in ROLE_GROUPS:
        if group in names:
            return role
    return None


# Session lifetime, in seconds: (idle, absolute). Idle counts from the last
# request, absolute from sign-in. Break-glass is short on purpose: it is only
# used when something is already wrong. The cookie itself is capped at 12h in
# main.py, so an absolute limit above that has no effect.
SESSION_LIMITS = {
    "default": (2 * 3600, 12 * 3600),
    "breakglass": (15 * 60, 3600),
}


def session_valid(user: dict, now: float) -> bool:
    """Whether a signed-in session may still be used.

    `user` carries "iat" (sign-in time) and "seen" (last request), both epoch
    seconds, plus "role" and "via" ("cf", "breakglass", "tailnet" or "direct").
    """
    idle, absolute = SESSION_LIMITS.get(user.get("via"), SESSION_LIMITS["default"])
    try:
        iat, seen = float(user["iat"]), float(user["seen"])
    except (KeyError, TypeError, ValueError):
        return False  # a session without timestamps is not one we issued
    return now - seen <= idle and now - iat <= absolute and iat <= now + 60


def via_of(headers, host: str) -> str:
    """How the request reached us. Informational only; never used to grant access."""
    if config.breakglass_host and host == config.breakglass_host:
        return "breakglass"
    if headers.get("x-ops-path") == "tailnet":
        return "tailnet"
    if headers.get("cf-ray"):
        return "cf"
    return "direct"


def pkce_pair(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def safe_next(target: str | None) -> str:
    """Only same-site relative paths, so /auth/login?next= cannot bounce elsewhere."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


_jwk_client = None


def verify_cf_access(token: str | None) -> dict:
    """Claims of a valid Cloudflare Access token for the break-glass app, else raise."""
    global _jwk_client
    import jwt  # PyJWT; imported lazily so the module loads without it in tests

    if not token or not config.cf_team_domain or not config.cf_breakglass_aud:
        raise PermissionError("no Cloudflare Access token or break-glass not configured")
    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(f"https://{config.cf_team_domain}/cdn-cgi/access/certs",
                                      cache_keys=True, lifespan=3600)
    key = _jwk_client.get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=["RS256"], audience=config.cf_breakglass_aud,
                      issuer=f"https://{config.cf_team_domain}")


# ── request-time checks ─────────────────────────────────────────────────────

async def current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="not signed in")
    return user


def require_role(minimum: str):
    async def dep(request: Request, user: dict = Depends(current_user)) -> dict:
        if RANK.get(user.get("role"), 0) < RANK[minimum]:
            await audit.record(request.scope, user, action="forbidden", target=request.url.path,
                               outcome="forbidden", status=403, detail={"needs": minimum})
            raise HTTPException(status_code=403, detail=f"this needs the {minimum} role")
        return user
    return dep


def _is_exempt(path: str) -> bool:
    return path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES)


def _is_page_load(path: str) -> bool:
    return not path.startswith(("/api/", "/assets/")) and "." not in path.rsplit("/", 1)[-1]


UNAUTH_DB_EVERY = 60  # seconds between persisted 401 rows per client address
_unauth_last: dict[str, float] = {}


class AuthMiddleware:
    """Session gate for HTTP and WebSocket. Must sit inside SessionMiddleware."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or _is_exempt(scope["path"]):
            return await self.app(scope, receive, send)

        session = scope.get("session", {})
        user = session.get("user")
        now = time.time()
        if user and session_valid(user, now):
            user["seen"] = now
            scope.setdefault("state", {})["user"] = user
            if scope["type"] == "websocket":
                await audit.record(scope, user, action="ws-connect", target=scope["path"])
            elif scope["method"] == "GET" and _is_page_load(scope["path"]):
                await audit.record(scope, user, action="page", target=scope["path"])
            elif scope["method"] not in ("GET", "HEAD", "OPTIONS") and not _same_origin(scope):
                await audit.record(scope, user, action="cross-origin", target=scope["path"],
                                   outcome="forbidden", status=403)
                return await JSONResponse({"detail": "cross-origin request refused"}, 403)(scope, receive, send)
            return await self.app(scope, receive, send)

        if user:
            session.pop("user", None)  # expired: force a fresh login
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return
        if scope["path"].startswith("/api/"):
            # A stale tab or a scanner can poll without a session every second.
            # Every attempt goes to the log (Loki); Postgres gets one row per
            # client per UNAUTH_DB_EVERY seconds so it cannot be flooded.
            ip = audit.client_ip(scope) or "?"
            persist = now - _unauth_last.get(ip, 0) >= UNAUTH_DB_EVERY
            if persist:
                _unauth_last[ip] = now
                if len(_unauth_last) > 10_000:
                    _unauth_last.clear()
            await audit.record(scope, None, action="request", target=scope["path"],
                               outcome="unauthenticated", status=401, persist=persist)
            return await JSONResponse({"detail": "not signed in"}, 401)(scope, receive, send)
        qs = scope.get("query_string", b"").decode()
        target = scope["path"] + ("?" + qs if qs else "")
        return await RedirectResponse("/auth/login?next=" + quote(target, safe=""), 302)(scope, receive, send)


def _same_origin(scope) -> bool:
    """Reject state-changing requests whose Origin is another site (CSRF backstop)."""
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    origin = headers.get("origin")
    if not origin:
        return True  # same-origin fetches from older browsers and non-browser clients
    host = headers.get("x-forwarded-host") or headers.get("host", "")
    return origin.split("://", 1)[-1].rstrip("/") == host


def public_user(user: dict) -> dict:
    return {k: user.get(k) for k in ("username", "email", "role", "via", "iat")}


def dumps(o) -> str:
    return json.dumps(o, default=str, separators=(",", ":"))
