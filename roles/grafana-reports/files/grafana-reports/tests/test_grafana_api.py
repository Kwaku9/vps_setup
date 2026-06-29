import json
from pathlib import Path
import httpx
import pytest
from grafana_reports.grafana_api import GrafanaAPI

FIX = Path(__file__).parent / "fixtures"

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://grafana.test")

@pytest.mark.asyncio
async def test_panels_of_extracts_id_title_type_and_skips_rows():
    dash = json.loads((FIX / "dashboard.json").read_text())

    def handler(request):
        assert request.url.path == "/api/dashboards/uid/crowdsec-threats"
        assert request.headers["Authorization"] == "Bearer sa-tok"
        return httpx.Response(200, json=dash)

    api = GrafanaAPI("http://grafana.test", "sa-tok", client=_client(handler))
    panels = await api.panels_of("crowdsec-threats")
    titles = {p["title"] for p in panels}
    assert "Cyber Attack Map" in titles
    assert all("id" in p and p["type"] != "row" for p in panels)

@pytest.mark.asyncio
async def test_search_returns_dashboards():
    search = json.loads((FIX / "search.json").read_text())
    api = GrafanaAPI("http://grafana.test", "sa-tok",
                     client=_client(lambda r: httpx.Response(200, json=search)))
    out = await api.search()
    assert any(d["uid"] == "crowdsec-threats" for d in out)
