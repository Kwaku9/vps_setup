from __future__ import annotations
from grafana_reports.config import Settings
from grafana_reports.grafana_api import GrafanaAPI
from grafana_reports.catalog import Catalog
from grafana_reports.store import Store
from grafana_reports.renderer import render
from grafana_reports.resolver import resolve, llm_resolve

class Engine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api = GrafanaAPI(settings.grafana_url, settings.grafana_sa_token)
        self.catalog = Catalog(settings.catalog_path, self.api)
        self.store = Store(settings)

    async def do_render(self, query=None, dashboard_uid=None, panel_id=None,
                        from_time=None, to_time=None, width=None, height=None,
                        variables=None) -> dict:
        s = self.settings
        label = ""
        if dashboard_uid is not None and panel_id is not None:
            frm = from_time or "now-6h"
            to = to_time or "now"
            p = self.catalog.find(dashboard_uid, panel_id)
            label = p.label if p else ""
        elif query is not None:
            cands = await resolve(query, self.catalog.get(), s, llm=llm_resolve)
            if not cands:
                raise ValueError("could not resolve query to a panel")
            c = cands[0]
            dashboard_uid, panel_id = c.dashboard_uid, c.panel_id
            frm = from_time or c.frm
            to = to_time or c.to
            label = c.label
        else:
            raise ValueError("provide either query or (dashboard_uid, panel_id)")
        w = width or s.default_width
        h = height or s.default_height
        png = await render(dashboard_uid, panel_id, frm, to, w, h, s, variables=variables)
        rid = self.store.save(png, {"dashboard_uid": dashboard_uid, "panel_id": panel_id,
                                    "from": frm, "to": to, "width": w, "height": h, "label": label,
                                    "variables": variables or {}})
        return {"png": png, "report_id": rid, "view_url": self.store.presign(rid),
                "label": label, "from": frm, "to": to}
