from __future__ import annotations
import httpx
from grafana_reports.config import Settings

class RenderError(Exception):
    pass

async def render(uid: str, panel_id: int, frm: str, to: str, width: int, height: int,
                 settings: Settings, client: httpx.AsyncClient | None = None) -> bytes:
    path = f"/render/d-solo/{uid}/"
    params = (f"orgId=1&panelId={panel_id}&from={frm}&to={to}"
              f"&width={width}&height={height}&timeout={settings.render_timeout}")
    url = f"{path}?{params}" if client is not None else f"{settings.grafana_url}{path}?{params}"
    headers = {"Authorization": f"Bearer {settings.grafana_sa_token}"}
    timeout = settings.render_timeout + 15
    try:
        if client is not None:
            resp = await client.get(url, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
                resp = await c.get(url, headers=headers)
    except httpx.HTTPError as e:
        raise RenderError(f"render request failed: {e}") from e
    if resp.status_code != 200:
        raise RenderError(f"grafana render HTTP {resp.status_code}")
    if "image" not in resp.headers.get("content-type", ""):
        raise RenderError(f"unexpected content-type {resp.headers.get('content-type')}")
    return resp.content
