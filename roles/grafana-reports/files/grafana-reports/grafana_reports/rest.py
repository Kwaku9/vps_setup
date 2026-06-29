from __future__ import annotations
import base64
from dataclasses import asdict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from grafana_reports.service import Engine
from grafana_reports.resolver import resolve, llm_resolve
from grafana_reports.renderer import RenderError

class ResolveBody(BaseModel):
    query: str

class ReportBody(BaseModel):
    query: str | None = None
    dashboard_uid: str | None = None
    panel_id: int | None = None
    from_time: str | None = None
    to_time: str | None = None
    width: int | None = None
    height: int | None = None

def build_router(engine: Engine) -> APIRouter:
    r = APIRouter()

    @r.get("/healthz")
    async def healthz():
        return {"ok": True, "categories": len(engine.catalog.get())}

    @r.get("/catalog")
    async def catalog():
        return {"categories": [asdict(c) for c in engine.catalog.get()]}

    @r.post("/resolve")
    async def resolve_ep(body: ResolveBody):
        cands = await resolve(body.query, engine.catalog.get(), engine.settings, llm=llm_resolve)
        return {"candidates": [asdict(c) for c in cands[:5]]}

    @r.post("/report")
    async def report(body: ReportBody):
        try:
            out = await engine.do_render(**body.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except RenderError as e:
            raise HTTPException(status_code=502, detail=f"render failed upstream: {e}")
        return {"report_id": out["report_id"], "view_url": out["view_url"],
                "png_base64": base64.b64encode(out["png"]).decode(),
                "label": out["label"], "from": out["from"], "to": out["to"]}

    @r.get("/report/{report_id}")
    async def report_url(report_id: str, ttl: int | None = None):
        if not engine.store.exists(report_id):
            raise HTTPException(status_code=404, detail="unknown report_id")
        return {"report_id": report_id, "view_url": engine.store.presign(report_id, ttl)}

    return r
