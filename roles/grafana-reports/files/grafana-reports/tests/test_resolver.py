import pytest
from grafana_reports.models import Category, Dashboard, Panel, Candidate
from grafana_reports.config import Settings
from grafana_reports.resolver import resolve

def _settings(**kw):
    base = dict(grafana_url="", grafana_sa_token="", auth_token="", s3_bucket=None,
                s3_prefix="reports", s3_region="us-east-1", presign_ttl=3600,
                litellm_url=None, litellm_model="m", litellm_key=None, catalog_path="",
                refresh_interval=900, default_width=1000, default_height=500,
                render_timeout=15, fuzzy_threshold=70)
    base.update(kw)
    return Settings(**base)

def _cats():
    return [Category(name="threats", label="Threats", dashboards=[Dashboard(
        uid="crowdsec-threats", title="t", panels=[
            Panel(12, "Cyber Attack Map", "Cyber Attack Map", ["attack map", "world map"], "geomap"),
            Panel(5, "Decisions over time", "Decisions over time", ["bans over time"], "timeseries"),
        ])])]

@pytest.mark.asyncio
async def test_fuzzy_picks_best_panel_and_parses_time():
    out = await resolve("show me the cyber attack map last 24h", _cats(), _settings())
    assert out[0].panel_id == 12
    assert (out[0].frm, out[0].to) == ("now-24h", "now")
    assert out[0].method == "fuzzy"
    assert out[0].confidence >= 70

@pytest.mark.asyncio
async def test_synonym_match():
    out = await resolve("world map", _cats(), _settings())
    assert out[0].panel_id == 12

@pytest.mark.asyncio
async def test_low_confidence_falls_back_to_llm_and_validates_membership():
    async def fake_llm(q, cats, s):
        return Candidate("threats", "crowdsec-threats", 5, "Decisions over time", "now-6h", "now", 0.9, "llm")
    out = await resolve("how are the bans trending", _cats(), _settings(fuzzy_threshold=95), llm=fake_llm)
    assert out[0].panel_id == 5 and out[0].method == "llm"

@pytest.mark.asyncio
async def test_llm_exception_falls_back_to_fuzzy():
    """I3 regression: if the injected llm raises, resolve() must return fuzzy list, not propagate."""
    async def boom(*a):
        raise RuntimeError("litellm down")
    out = await resolve("cyber attack map", _cats(), _settings(fuzzy_threshold=5), llm=boom)
    assert len(out) > 0
    assert all(c.method == "fuzzy" for c in out)

@pytest.mark.asyncio
async def test_llm_hallucination_rejected():
    async def fake_llm(q, cats, s):
        return Candidate("threats", "crowdsec-threats", 999, "Ghost", "now-6h", "now", 0.9, "llm")
    out = await resolve("nonsense query zzz", _cats(), _settings(fuzzy_threshold=95), llm=fake_llm)
    # 999 doesn't exist → llm result rejected → fuzzy list returned instead
    assert all(c.panel_id != 999 for c in out)
