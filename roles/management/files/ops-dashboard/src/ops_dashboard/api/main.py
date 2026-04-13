"""FastAPI application for the Ops Dashboard web interface."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .dependencies import init_state
from .routers import actions, metrics, profiles, services, stacks
from .victoria import VictoriaMetricsClient
from .ws.metrics_stream import metrics_poll_loop

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    state = init_state()
    logger.info(
        f"Loaded {len(state.services)} services, "
        f"{len(state.profiles)} profiles, "
        f"{len(state.stacks)} stacks"
    )

    # Start Victoria Metrics poller
    vm_client = VictoriaMetricsClient()
    poll_task = asyncio.create_task(
        metrics_poll_loop(
            ws_manager=metrics.ws_manager,
            vm_client=vm_client,
            metrics_cache=state.metrics_cache,
            interval=5.0,
        )
    )
    state._poll_task = poll_task

    yield

    # Shutdown
    poll_task.cancel()
    await vm_client.close()
    logger.info("Ops Dashboard API shutdown")


app = FastAPI(
    title="Ops Dashboard API",
    description="Operational profiles and service management",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(services.router)
app.include_router(profiles.router)
app.include_router(stacks.router)
app.include_router(actions.router)
app.include_router(metrics.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}


# Serve frontend static files in production
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
