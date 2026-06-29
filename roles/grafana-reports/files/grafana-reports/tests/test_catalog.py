import json, yaml
from pathlib import Path
import httpx, pytest
from grafana_reports.grafana_api import GrafanaAPI
from grafana_reports.catalog import build_catalog, load_curation

FIX = Path(__file__).parent / "fixtures"

def _api():
    dash = json.loads((FIX / "dashboard.json").read_text())
    def handler(request):
        return httpx.Response(200, json=dash)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://g.test")
    return GrafanaAPI("http://g.test", "t", client=client)

@pytest.mark.asyncio
async def test_build_catalog_resolves_titles_to_live_ids_and_applies_labels():
    curation = load_curation(str(FIX / "catalog.yml"))
    cats = await build_catalog(curation, _api())
    assert len(cats) == 1
    cat = cats[0]
    assert cat.name == "threats" and cat.label == "Threats"
    panels = {p.label: p for p in cat.dashboards[0].panels}
    # "Cyber Attack Map" resolved to live panel id 12 from dashboard.json
    assert panels["Cyber Attack Map"].panel_id == 12
    assert "attack map" in panels["Cyber Attack Map"].synonyms
    # Curated entry with no explicit label falls back to the Grafana title
    assert "Decisions over time" in panels
    assert panels["Decisions over time"].panel_id == 5

@pytest.mark.asyncio
async def test_curated_title_absent_in_grafana_is_skipped_not_fatal(caplog):
    curation = {"categories": {"threats": {"label": "Threats", "dashboards": [
        {"uid": "crowdsec-threats", "expose": [{"title": "Nonexistent Panel"}]}]}}}
    cats = await build_catalog(curation, _api())
    assert cats[0].dashboards[0].panels == []
