from __future__ import annotations
import httpx

class GrafanaAPI:
    def __init__(self, base_url: str, token: str, client: httpx.AsyncClient | None = None):
        self._base = base_url.rstrip("/")
        self._token = token
        self._client = client
        self._owns_client = client is None

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    async def _get(self, path: str) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(path, headers=self._headers())
        async with httpx.AsyncClient(base_url=self._base, timeout=30) as c:
            return await c.get(path, headers=self._headers())

    async def search(self) -> list[dict]:
        resp = await self._get("/api/search?type=dash-db")
        resp.raise_for_status()
        return resp.json()

    async def dashboard(self, uid: str) -> dict:
        resp = await self._get(f"/api/dashboards/uid/{uid}")
        resp.raise_for_status()
        return resp.json()

    async def panels_of(self, uid: str) -> list[dict]:
        dash = (await self.dashboard(uid)).get("dashboard", {})
        out = []
        for p in dash.get("panels", []):
            if p.get("type") == "row" or "id" not in p:
                continue
            out.append({"id": p["id"], "title": p.get("title", ""), "type": p.get("type", "")})
        return out
