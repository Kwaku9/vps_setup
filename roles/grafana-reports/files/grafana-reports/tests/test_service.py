import pytest
from grafana_reports.config import Settings
from grafana_reports.service import Engine
from grafana_reports.models import Category, Dashboard, Panel

def _s(tmp):
    return Settings(grafana_url="http://g", grafana_sa_token="sa", auth_token="a", s3_bucket=None,
                    s3_prefix="reports", s3_region="us-east-1", presign_ttl=3600, litellm_url=None,
                    litellm_model="m", litellm_key=None, catalog_path="", refresh_interval=900,
                    default_width=1000, default_height=500, render_timeout=15, fuzzy_threshold=70)

@pytest.mark.asyncio
async def test_do_render_resolves_query_then_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    eng = Engine(_s(tmp_path))
    # inject catalog directly (skip Grafana discovery)
    eng.catalog._categories = [Category("threats", "Threats", [Dashboard("crowdsec-threats", "t",
        [Panel(12, "Cyber Attack Map", "Cyber Attack Map", ["attack map"], "geomap")])])]
    async def fake_render(uid, pid, frm, to, w, h, settings, client=None, variables=None):
        assert (uid, pid) == ("crowdsec-threats", 12)
        return b"\x89PNG-bytes"
    monkeypatch.setattr("grafana_reports.service.render", fake_render)
    out = await eng.do_render(query="cyber attack map last 24h")
    assert out["png"] == b"\x89PNG-bytes"
    assert out["from"] == "now-24h"
    assert len(out["report_id"]) == 64  # sha256 hex

@pytest.mark.asyncio
async def test_do_render_explicit_ids_skip_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    eng = Engine(_s(tmp_path))
    seen = {}
    async def fake_render(uid, pid, frm, to, w, h, settings, client=None, variables=None):
        seen["variables"] = variables
        return b"PNGX"
    monkeypatch.setattr("grafana_reports.service.render", fake_render)
    out = await eng.do_render(dashboard_uid="u", panel_id=3, from_time="now-1h", to_time="now",
                              variables={"container": "crowdsec"})
    assert out["report_id"]
    # template variables flow through to the renderer (the crowdsec-memory path)
    assert seen["variables"] == {"container": "crowdsec"}
