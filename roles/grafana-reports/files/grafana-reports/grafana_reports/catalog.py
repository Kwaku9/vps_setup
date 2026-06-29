from __future__ import annotations
import asyncio, logging
import yaml
from grafana_reports.grafana_api import GrafanaAPI
from grafana_reports.models import Panel, Dashboard, Category

log = logging.getLogger("grafana_reports.catalog")

def load_curation(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}

async def build_catalog(curation: dict, api: GrafanaAPI) -> list[Category]:
    categories: list[Category] = []
    for tag, cat_def in (curation.get("categories") or {}).items():
        dashboards: list[Dashboard] = []
        for d in cat_def.get("dashboards", []):
            uid = d["uid"]
            try:
                live = {p["title"]: p for p in await api.panels_of(uid)}
            except Exception:
                log.warning("catalog: could not load dashboard %s; skipping", uid)
                continue
            panels: list[Panel] = []
            for entry in d.get("expose", []):
                title = entry["title"]
                lp = live.get(title)
                if lp is None:
                    log.warning("catalog: curated panel %r not found in %s; skipping", title, uid)
                    continue
                panels.append(Panel(
                    panel_id=lp["id"],
                    title=title,
                    label=entry.get("label", title),
                    synonyms=entry.get("synonyms", []),
                    panel_type=lp.get("type", ""),
                ))
            dashboards.append(Dashboard(uid=uid, title=uid, panels=panels))
        categories.append(Category(name=tag, label=cat_def.get("label", tag), dashboards=dashboards))
    return categories

class Catalog:
    def __init__(self, curation_path: str, api: GrafanaAPI):
        self._path = curation_path
        self._api = api
        self._categories: list[Category] = []

    async def refresh(self) -> None:
        curation = load_curation(self._path)
        self._categories = await build_catalog(curation, self._api)
        log.info("catalog refreshed: %d categories", len(self._categories))

    def get(self) -> list[Category]:
        return self._categories

    def find(self, dashboard_uid: str, panel_id: int) -> Panel | None:
        for c in self._categories:
            for d in c.dashboards:
                if d.uid != dashboard_uid:
                    continue
                for p in d.panels:
                    if p.panel_id == panel_id:
                        return p
        return None
