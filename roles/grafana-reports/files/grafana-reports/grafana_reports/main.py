from __future__ import annotations
import asyncio, logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from grafana_reports.config import Settings
from grafana_reports.service import Engine
from grafana_reports.mcp_server import build_mcp
from grafana_reports.rest import build_router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grafana_reports")

def create_app() -> FastAPI:
    settings = Settings.from_env()
    engine = Engine(settings)
    mcp = build_mcp(engine)
    mcp_app = mcp.http_app(path="/mcp")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await engine.catalog.refresh()
        except Exception:
            log.exception("initial catalog refresh failed")
        task = asyncio.create_task(_refresh_loop(engine))
        async with mcp_app.lifespan(app):
            yield
        task.cancel()

    app = FastAPI(title="grafana-reports", lifespan=lifespan)

    @app.middleware("http")
    async def bearer_auth(request: Request, call_next):
        # /mcp handles its own auth header; guard the REST routes
        if not request.url.path.startswith("/mcp") and request.url.path != "/healthz":
            expected = f"Bearer {settings.auth_token}"
            if settings.auth_token and request.headers.get("Authorization") != expected:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    # FastAPI 0.100+ wraps include_router routes in _IncludedRouter (no .path attr),
    # which breaks `{r.path for r in app.routes}` introspection in the smoke test.
    # Add routes individually via add_api_route so they appear as Route objects.
    for route in build_router(engine).routes:
        app.add_api_route(route.path, route.endpoint, methods=list(route.methods))
    app.mount("/mcp", mcp_app)
    return app

async def _refresh_loop(engine: Engine):
    while True:
        await asyncio.sleep(engine.settings.refresh_interval)
        try:
            await engine.catalog.refresh()
        except Exception:
            log.exception("catalog refresh failed")

app = create_app()

if __name__ == "__main__":
    uvicorn.run("grafana_reports.main:app", host="0.0.0.0", port=8765, log_level="info")
