import base64, pytest
from fastapi.testclient import TestClient
from grafana_reports.config import Settings
from grafana_reports.service import Engine
from grafana_reports.rest import build_router
from grafana_reports.models import Category, Dashboard, Panel
from fastapi import FastAPI

def _engine(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    s = Settings(grafana_url="http://g", grafana_sa_token="sa", auth_token="", s3_bucket=None,
                 s3_prefix="reports", s3_region="us-east-1", presign_ttl=3600, litellm_url=None,
                 litellm_model="m", litellm_key=None, catalog_path="", refresh_interval=900,
                 default_width=1000, default_height=500, render_timeout=15, fuzzy_threshold=70)
    eng = Engine(s)
    eng.catalog._categories = [Category("threats", "Threats", [Dashboard("crowdsec-threats", "t",
        [Panel(12, "Cyber Attack Map", "Cyber Attack Map", ["attack map"], "geomap")])])]
    return eng

def _client(eng):
    app = FastAPI(); app.include_router(build_router(eng)); return TestClient(app)

def test_catalog_endpoint(tmp_path, monkeypatch):
    c = _client(_engine(tmp_path, monkeypatch))
    r = c.get("/catalog")
    assert r.status_code == 200
    assert r.json()["categories"][0]["name"] == "threats"

def test_report_endpoint_returns_base64_png(tmp_path, monkeypatch):
    eng = _engine(tmp_path, monkeypatch)
    async def fake_render(uid, pid, frm, to, w, h, settings, client=None):
        return b"\x89PNG-data"
    monkeypatch.setattr("grafana_reports.service.render", fake_render)
    c = _client(eng)
    r = c.post("/report", json={"query": "cyber attack map last 24h"})
    assert r.status_code == 200
    body = r.json()
    assert base64.b64decode(body["png_base64"]) == b"\x89PNG-data"
    assert body["from"] == "now-24h" and len(body["report_id"]) == 64

def test_report_render_failure_maps_to_502(tmp_path, monkeypatch):
    from grafana_reports.renderer import RenderError
    eng = _engine(tmp_path, monkeypatch)
    async def boom(uid, pid, frm, to, w, h, settings, client=None):
        raise RenderError("grafana render HTTP 500")
    monkeypatch.setattr("grafana_reports.service.render", boom)
    c = _client(eng)
    r = c.post("/report", json={"query": "cyber attack map last 24h"})
    assert r.status_code == 502
    assert "render failed" in r.json()["detail"]
