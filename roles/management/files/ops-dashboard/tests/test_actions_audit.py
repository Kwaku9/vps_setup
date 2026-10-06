from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ops_dashboard.api import audit, auth
from ops_dashboard.api.dependencies import get_state
from ops_dashboard.api.routers import actions


class FakeProvider:
    def __init__(self, ok=True):
        self.ok = ok

    async def start_service(self, svc):
        return self.ok, "started" if self.ok else "podman start failed"

    async def stop_service(self, svc):
        return self.ok, "stopped" if self.ok else "podman stop failed"


def make(role, *, pool=object(), ok=True, monkeypatch=None):
    events, alerts = [], []

    async def fake_record(scope, user, persist=True, **kw):
        events.append({"user": (user or {}).get("username"), **kw})

    monkeypatch.setattr(audit, "record", fake_record)
    monkeypatch.setattr(audit, "notify", lambda provider, text: alerts.append(text))

    svc = SimpleNamespace(name="grafana", platform=SimpleNamespace(value="vps"), pod="metrics-pod")
    state = SimpleNamespace(services={"grafana": svc}, vps_provider=FakeProvider(ok), azure_provider=None)
    app = FastAPI()
    app.state.db_pool = pool
    app.include_router(actions.router)
    app.dependency_overrides[get_state] = lambda: state
    app.dependency_overrides[auth.current_user] = lambda: {"username": "kb", "role": role, "via": "cf"}
    return TestClient(app), events, alerts


def test_operator_can_start_and_it_is_audited_and_alerted(monkeypatch):
    c, events, alerts = make("operator", monkeypatch=monkeypatch)
    r = c.post("/api/actions/start/grafana")
    assert r.status_code == 200 and r.json()["success"] is True
    assert events[-1]["action"] == "start" and events[-1]["outcome"] == "ok"
    assert events[-1]["detail"]["command"] == "podman start grafana"
    assert len(alerts) == 1 and "podman start grafana" in alerts[0] and "kb" in alerts[0]


def test_operator_cannot_stop(monkeypatch):
    c, events, alerts = make("operator", monkeypatch=monkeypatch)
    assert c.post("/api/actions/stop/grafana").status_code == 403
    assert events[-1]["outcome"] == "forbidden"
    assert alerts == []


def test_admin_stop_records_the_exact_command(monkeypatch):
    c, events, alerts = make("admin", monkeypatch=monkeypatch)
    assert c.post("/api/actions/stop/grafana").status_code == 200
    assert events[-1]["detail"]["command"] == "podman stop -t 2 grafana"


def test_failed_action_is_audited_as_failed(monkeypatch):
    c, events, alerts = make("admin", ok=False, monkeypatch=monkeypatch)
    r = c.post("/api/actions/stop/grafana")
    assert r.json()["success"] is False
    assert events[-1]["outcome"] == "failed"
    assert "FAILED" in alerts[0]


def test_actions_pause_when_audit_is_unavailable(monkeypatch):
    c, events, alerts = make("admin", pool=None, monkeypatch=monkeypatch)
    assert c.post("/api/actions/stop/grafana").status_code == 503
    assert alerts == []


def test_unknown_service_is_audited_as_refused(monkeypatch):
    c, events, alerts = make("admin", monkeypatch=monkeypatch)
    assert c.post("/api/actions/start/nope").status_code == 404
    assert events[-1]["outcome"] == "refused"


def test_audit_logger_emits_info_on_its_own():
    import logging
    lg = logging.getLogger("ops_audit")
    assert lg.isEnabledFor(logging.INFO)          # not filtered by uvicorn's WARNING root
    assert lg.propagate is False
    assert any(isinstance(h, logging.StreamHandler) for h in lg.handlers)
