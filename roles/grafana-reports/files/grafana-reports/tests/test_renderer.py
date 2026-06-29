import httpx, pytest
from grafana_reports.renderer import render, RenderError
from grafana_reports.config import Settings

def _s():
    return Settings(grafana_url="http://g.test", grafana_sa_token="sa", auth_token="",
                    s3_bucket=None, s3_prefix="r", s3_region="us-east-1", presign_ttl=3600,
                    litellm_url=None, litellm_model="m", litellm_key=None, catalog_path="",
                    refresh_interval=900, default_width=1000, default_height=500,
                    render_timeout=15, fuzzy_threshold=70)

@pytest.mark.asyncio
async def test_render_builds_d_solo_url_with_auth_and_returns_png():
    seen = {}
    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://g.test")
    out = await render("crowdsec-threats", 12, "now-24h", "now", 1000, 500, _s(), client=client)
    assert out.startswith(b"\x89PNG")
    assert "/render/d-solo/crowdsec-threats/" in seen["url"]
    assert "panelId=12" in seen["url"] and "from=now-24h" in seen["url"]
    assert seen["auth"] == "Bearer sa"

@pytest.mark.asyncio
async def test_render_raises_on_non_image():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")),
        base_url="http://g.test")
    with pytest.raises(RenderError):
        await render("u", 1, "now-1h", "now", 100, 100, _s(), client=client)
