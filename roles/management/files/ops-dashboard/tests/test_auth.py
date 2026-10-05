import time

import httpx
import pytest
from fastapi import Depends, FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from starlette.websockets import WebSocketDisconnect

from ops_dashboard.api import audit, auth
from ops_dashboard.api.routers import auth as auth_router


@pytest.fixture
def events(monkeypatch):
    """Capture audit events instead of writing them."""
    got = []

    async def fake_record(scope, user, **kw):
        got.append({"user": (user or {}).get("username"), **kw})
        return kw

    monkeypatch.setattr(audit, "record", fake_record)
    return got


@pytest.fixture
def always_valid(monkeypatch):
    monkeypatch.setattr(auth, "session_valid", lambda user, now: True)


def make_app():
    app = FastAPI()
    app.state.db_pool = None

    @app.get("/test/login/{role}")  # test-only: plant a session
    async def plant(role: str, request: Request):
        now = time.time()
        request.session["user"] = {"username": f"u-{role}", "role": role, "via": "cf", "iat": now, "seen": now}
        return {"ok": True}

    @app.get("/api/thing")
    async def thing():
        return {"ok": True}

    @app.post("/api/admin-only")
    async def admin_only(user: dict = Depends(auth.require_role("admin"))):
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/")
    async def index():
        return {"page": True}

    @app.websocket("/api/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_json({"hello": True})
        await socket.close()

    app.include_router(auth_router.router)
    # /test/login must bypass the gate to plant a session.
    auth.EXEMPT_PREFIXES = ("/auth/", "/test/")
    app.add_middleware(auth.AuthMiddleware)
    app.add_middleware(SessionMiddleware, secret_key="k", session_cookie="ops_session", https_only=True)
    return app


@pytest.fixture
def client():
    return TestClient(make_app(), base_url="https://ops.example")


# ── pure functions ──────────────────────────────────────────────────────────

def test_role_for_highest_group_wins():
    assert auth.role_for(["ops-viewers", "admins"]) == "admin"
    assert auth.role_for(["ops-operators", "ops-viewers"]) == "operator"
    assert auth.role_for(["ops-viewers"]) == "viewer"
    assert auth.role_for(["free_users"]) is None
    assert auth.role_for(None) is None


@pytest.mark.parametrize("raw,want", [
    ("/services", "/services"), ("https://evil.example", "/"), ("//evil.example", "/"),
    ("/\\evil", "/"), ("", "/"), (None, "/"),
])
def test_safe_next_only_allows_local_paths(raw, want):
    assert auth.safe_next(raw) == want


# ── the gate ────────────────────────────────────────────────────────────────

def test_unauthenticated_api_is_401_and_audited(client, events, always_valid):
    r = client.get("/api/thing")
    assert r.status_code == 401
    assert events[-1]["outcome"] == "unauthenticated"


def test_unauthenticated_page_redirects_to_login(client, always_valid):
    r = client.get("/?tab=x", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/auth/login?next=%2F%3Ftab%3Dx"


def test_health_stays_open(client):
    assert client.get("/api/health").status_code == 200


def test_unauthenticated_websocket_is_refused(client, always_valid):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws"):
            pass


def test_signed_in_page_load_is_audited(client, events, always_valid):
    client.get("/test/login/viewer")
    r = client.get("/")
    assert r.status_code == 200
    assert events[-1] == {"user": "u-viewer", "action": "page", "target": "/"}


def test_signed_in_websocket_connects(client, events, always_valid):
    client.get("/test/login/viewer")
    # The test client's jar does not attach Secure cookies to ws:// upgrades the
    # way a browser does on wss://, so hand the cookie over explicitly.
    cookie = {"cookie": f"ops_session={client.cookies['ops_session']}"}
    with client.websocket_connect("/api/ws", headers=cookie) as ws:
        assert ws.receive_json() == {"hello": True}
    assert events[-1]["action"] == "ws-connect"


def test_expired_session_is_dropped(client, monkeypatch, always_valid):
    client.get("/test/login/admin")
    monkeypatch.setattr(auth, "session_valid", lambda user, now: False)
    assert client.get("/api/thing").status_code == 401


def test_role_below_minimum_is_403_and_audited(client, events, always_valid):
    client.get("/test/login/operator")
    r = client.post("/api/admin-only", headers={"origin": "https://ops.example"})
    assert r.status_code == 403
    assert events[-1]["outcome"] == "forbidden"
    assert events[-1]["detail"] == {"needs": "admin"}


def test_admin_passes(client, always_valid):
    client.get("/test/login/admin")
    assert client.post("/api/admin-only", headers={"origin": "https://ops.example"}).status_code == 200


def test_cross_origin_post_is_refused(client, events, always_valid):
    client.get("/test/login/admin")
    r = client.post("/api/admin-only", headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert events[-1]["action"] == "cross-origin"


# ── OIDC login ──────────────────────────────────────────────────────────────

@pytest.fixture
def oidc(monkeypatch):
    for k, v in dict(client_id="cid", client_secret="sec", authorize_url="https://idp/authorize",
                     token_url="http://idp/token", userinfo_url="http://idp/userinfo",
                     redirect_url="https://ops.example/auth/callback", breakglass_host="").items():
        monkeypatch.setattr(auth.config, k, v)


def fake_idp(monkeypatch, claims):
    def handler(request: httpx.Request):
        if request.url.path == "/token":
            body = request.content.decode()
            assert "code_verifier=" in body and "client_secret=sec" in body
            return httpx.Response(200, json={"access_token": "at"})
        assert request.headers["authorization"] == "Bearer at"
        return httpx.Response(200, json=claims)

    real = httpx.AsyncClient
    monkeypatch.setattr(auth_router.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def start_login(client, next_="/sessions"):
    r = client.get(f"/auth/login?next={next_}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://idp/authorize?")
    return dict(p.split("=", 1) for p in r.headers["location"].split("?", 1)[1].split("&"))


def test_oidc_login_sets_session_and_returns_to_next(client, monkeypatch, oidc, events, always_valid):
    fake_idp(monkeypatch, {"preferred_username": "kb", "email": "kb@x", "groups": ["admins"]})
    q = start_login(client)
    assert q["code_challenge_method"] == "S256"
    r = client.get(f"/auth/callback?code=c&state={q['state']}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/sessions"
    me = client.get("/api/me").json()
    assert me["username"] == "kb" and me["role"] == "admin"
    assert any(e["action"] == "login" and e.get("outcome", "ok") == "ok" for e in events)


def test_oidc_state_mismatch_is_refused(client, oidc, events):
    start_login(client)
    r = client.get("/auth/callback?code=c&state=wrong", follow_redirects=False)
    assert r.status_code == 400
    assert events[-1]["outcome"] == "failed"


def test_oidc_user_without_ops_group_is_refused(client, monkeypatch, oidc, events, always_valid):
    fake_idp(monkeypatch, {"preferred_username": "guest", "groups": ["free_users"]})
    q = start_login(client)
    r = client.get(f"/auth/callback?code=c&state={q['state']}", follow_redirects=False)
    assert r.status_code == 403
    assert events[-1]["outcome"] == "forbidden" and events[-1]["user"] == "guest"
    assert client.get("/api/me").status_code == 401


# ── break-glass login ───────────────────────────────────────────────────────

@pytest.fixture
def breakglass(monkeypatch):
    monkeypatch.setattr(auth.config, "breakglass_host", "breakglass.example")
    monkeypatch.setattr(auth.config, "breakglass_emails", {"owner@x"})
    return TestClient(make_app(), base_url="https://breakglass.example")


def test_breakglass_requires_a_valid_cf_token(breakglass, monkeypatch, events):
    def bad(token):
        raise PermissionError("bad")
    monkeypatch.setattr(auth_router, "verify_cf_access", bad)
    r = breakglass.get("/auth/login", headers={"cf-access-authenticated-user-email": "owner@x"},
                       follow_redirects=False)
    assert r.status_code == 401  # the forgeable email header alone is not enough


def test_breakglass_rejects_unlisted_email(breakglass, monkeypatch, events):
    monkeypatch.setattr(auth_router, "verify_cf_access", lambda t: {"email": "someone@else"})
    r = breakglass.get("/auth/login", headers={"cf-access-jwt-assertion": "t"}, follow_redirects=False)
    assert r.status_code == 403


def test_breakglass_listed_email_gets_admin(breakglass, monkeypatch, events, always_valid):
    monkeypatch.setattr(auth_router, "verify_cf_access", lambda t: {"email": "Owner@X"})
    r = breakglass.get("/auth/login?next=/x", headers={"cf-access-jwt-assertion": "t"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/x"
    me = breakglass.get("/api/me").json()
    assert me == {**me, "username": "owner@x", "role": "admin", "via": "breakglass"}


def test_logout_clears_session(client, events, always_valid):
    client.get("/test/login/admin")
    assert client.post("/auth/logout").json()["ok"] is True
    assert client.get("/api/me").status_code == 401


# ── session lifetime ────────────────────────────────────────────────────────

@pytest.mark.parametrize("via,signed_in_ago,idle_for,ok", [
    ("cf", 60, 60, True),
    ("cf", 3 * 3600, 3600, True),           # active for 3h, idle 1h
    ("cf", 3 * 3600, 2 * 3600 + 1, False),  # idle past 2h
    ("cf", 12 * 3600 + 1, 10, False),       # past the 12h absolute cap
    ("breakglass", 600, 600, True),
    ("breakglass", 1200, 16 * 60, False),   # break-glass idle past 15 min
    ("breakglass", 3601, 10, False),        # break-glass past 1h
])
def test_session_valid_limits(via, signed_in_ago, idle_for, ok):
    now = 1_000_000.0
    user = {"via": via, "iat": now - signed_in_ago, "seen": now - idle_for}
    assert auth.session_valid(user, now) is ok


def test_session_without_timestamps_is_invalid():
    assert auth.session_valid({"via": "cf"}, 1_000_000.0) is False


def test_session_from_the_future_is_invalid():
    now = 1_000_000.0
    assert auth.session_valid({"via": "cf", "iat": now + 3600, "seen": now}, now) is False
