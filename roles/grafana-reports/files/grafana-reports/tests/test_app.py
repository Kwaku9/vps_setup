"""C1+I1 regression: /mcp route exists (no double-prefix 404) and is auth-guarded."""
from __future__ import annotations
import os
import pytest
from fastapi.testclient import TestClient


def _make_client(monkeypatch) -> tuple[TestClient, str]:
    token = "test-tok"
    monkeypatch.setenv("AUTH_TOKEN", token)
    monkeypatch.setenv("GRAFANA_SA_TOKEN", "x")
    monkeypatch.setenv("GRAFANA_URL", "http://127.0.0.1:19999")  # unreachable — lifespan tolerates it
    monkeypatch.setenv("LOCAL_DIR", "/tmp/gr-test-renders")
    # Import after env is set so Settings.from_env() picks up overrides
    from grafana_reports.main import create_app
    app = create_app()
    return TestClient(app, raise_server_exceptions=False), token


def test_healthz_no_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    client, _ = _make_client(monkeypatch)
    with client:
        r = client.get("/healthz")
    assert r.status_code == 200


def test_catalog_requires_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    client, _ = _make_client(monkeypatch)
    with client:
        r = client.get("/catalog")
    assert r.status_code == 401


def test_mcp_no_auth_returns_401_not_404(monkeypatch, tmp_path):
    """C1+I1: /mcp must exist (not 404) AND must require auth (401 without token)."""
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    client, _ = _make_client(monkeypatch)
    with client:
        r = client.post("/mcp")
    assert r.status_code == 401, f"expected 401 got {r.status_code}"


def test_mcp_with_auth_is_reachable(monkeypatch, tmp_path):
    """C1: POST /mcp with a valid bearer token must NOT be 404 (route exists)."""
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    client, token = _make_client(monkeypatch)
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    with client:
        r = client.post(
            "/mcp",
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
        )
    assert r.status_code != 404, f"route missing — got 404 (double-prefix bug still present)"
    assert r.status_code != 401, f"auth rejected with valid token"
