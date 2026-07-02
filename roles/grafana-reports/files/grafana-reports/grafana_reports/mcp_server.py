from __future__ import annotations
from dataclasses import asdict
from fastmcp import FastMCP
from fastmcp.utilities.types import Image  # NOT `from fastmcp import Image` — moved in 2.x/3.x
from grafana_reports.service import Engine
from grafana_reports.resolver import resolve, llm_resolve

def build_mcp(engine: Engine) -> FastMCP:
    mcp = FastMCP("grafana-reports")

    @mcp.tool
    async def render_panel(query: str | None = None, dashboard_uid: str | None = None,
                           panel_id: int | None = None, from_time: str | None = None,
                           to_time: str | None = None, width: int | None = None,
                           height: int | None = None,
                           variables: dict | None = None) -> list:
        """Render a Grafana panel to a PNG. Give a natural-language `query`
        (e.g. 'cyber attack map last 24h') OR explicit `dashboard_uid`+`panel_id`.
        `variables` binds Grafana template variables a panel exposes (see
        list_catalog `variables`), e.g. {"container": "crowdsec"} for the
        container memory panel. `from_time`/`to_time` take Grafana syntax
        (e.g. 'now-7d', 'now')."""
        r = await engine.do_render(query=query, dashboard_uid=dashboard_uid, panel_id=panel_id,
                                   from_time=from_time, to_time=to_time, width=width, height=height,
                                   variables=variables)
        meta = {"report_id": r["report_id"], "view_url": r["view_url"],
                "label": r["label"], "from": r["from"], "to": r["to"]}
        return [Image(data=r["png"], format="png"), meta]

    @mcp.tool
    def list_catalog(category: str | None = None) -> dict:
        """List the curated categories, dashboards, and panels available to render."""
        cats = engine.catalog.get()
        if category:
            cats = [c for c in cats if c.name == category]
        return {"categories": [asdict(c) for c in cats]}

    @mcp.tool
    async def resolve_query(query: str) -> dict:
        """Return ranked candidate panels for a query without rendering."""
        cands = await resolve(query, engine.catalog.get(), engine.settings, llm=llm_resolve)
        return {"candidates": [asdict(c) for c in cands[:5]]}

    @mcp.tool
    def report_url(report_id: str, ttl: int | None = None) -> dict:
        """Mint a fresh pre-signed URL for a previously rendered report_id."""
        return {"report_id": report_id, "view_url": engine.store.presign(report_id, ttl)}

    return mcp
