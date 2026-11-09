"""Request desk boundary: requesters need a verified Access token, admins need a session."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from ops_dashboard.api import audit, auth
from ops_dashboard.api.routers import access_requests


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    async def fake_record(scope, user, persist=True, **kw):
        return kw
    monkeypatch.setattr(audit, "record", fake_record)
    monkeypatch.setenv("CF_ACCESS_REQUEST_AUD", "aud-test")
    monkeypatch.setattr(auth.config, "cf_team_domain", "team.example")


@pytest.fixture
def client():
    app = FastAPI()
    app.state.db_pool = None
    app.include_router(access_requests.router)
    app.add_middleware(auth.AuthMiddleware)
    app.add_middleware(SessionMiddleware, secret_key="k", session_cookie="ops_session", https_only=True)
    return TestClient(app, base_url="https://portal.example", follow_redirects=False)


def test_page_is_served_without_a_dashboard_session(client):
    r = client.get("/request/")
    assert r.status_code == 200 and "Request access" in r.text


def test_bare_path_redirects_to_the_page(client):
    assert client.get("/request").headers["location"] == "/request/"


def test_requester_api_refuses_without_token(client):
    assert client.get("/request/api/me").status_code == 401


def test_forged_email_header_is_not_trusted(client):
    r = client.get("/request/api/me", headers={"Cf-Access-Authenticated-User-Email": "owner@example.com"})
    assert r.status_code == 401


def test_garbage_token_is_refused(client):
    r = client.get("/request/api/me", headers={"Cf-Access-Jwt-Assertion": "not.a.jwt"})
    assert r.status_code == 401


def test_cross_origin_post_is_refused(client):
    r = client.post("/request/api/requests", json={"kind": "students", "reason": "x" * 20},
                    headers={"Origin": "https://evil.example", "Cf-Access-Jwt-Assertion": "not.a.jwt"})
    assert r.status_code == 403


def test_same_origin_post_still_needs_a_token(client):
    # Control for the test above: same origin passes the CSRF check and fails on identity.
    r = client.post("/request/api/requests", json={"kind": "students", "reason": "x" * 20},
                    headers={"Origin": "https://portal.example"})
    assert r.status_code == 401


def test_admin_list_needs_a_session(client):
    assert client.get("/api/access-requests").status_code == 401


def test_admin_decide_needs_a_session(client):
    assert client.post("/api/access-requests/1/decide", json={"decision": "approve"}).status_code == 401


def test_exemption_is_only_the_request_prefix(client):
    # /requestx must not slip past the session gate by sharing a prefix.
    assert auth._is_exempt("/request/api/me") and auth._is_exempt("/request")
    assert not auth._is_exempt("/requestx") and not auth._is_exempt("/api/access-requests")
