import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ops_dashboard.api.routers import ingest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SESSION_INGEST_TOKEN", "test-token")

    captured = {}

    async def fake_handle(pool, payload):
        captured["payload"] = payload
        return {"session_uuid": payload["session_uuid"], "live_status": "running"}

    monkeypatch.setattr(ingest, "handle_ingest", fake_handle)
    app = FastAPI()
    app.state.db_pool = None
    app.include_router(ingest.router)
    return TestClient(app), captured


def test_ingest_rejects_without_token(client):
    c, _ = client
    r = c.post("/api/sessions/ingest", json={"session_uuid": "x", "event_type": "Stop"})
    assert r.status_code == 401


def test_ingest_accepts_with_token(client):
    c, captured = client
    r = c.post(
        "/api/sessions/ingest",
        headers={"Authorization": "Bearer test-token"},
        json={"session_uuid": "x", "event_type": "Stop", "transcript_delta": [], "cwd": "/w"},
    )
    assert r.status_code == 200
    assert captured["payload"]["event_type"] == "Stop"
