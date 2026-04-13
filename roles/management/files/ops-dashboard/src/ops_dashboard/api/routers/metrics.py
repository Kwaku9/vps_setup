"""Metrics REST fallback and WebSocket endpoint."""

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ..dependencies import DashboardState, get_state
from ..schemas import MetricsSnapshot
from ..ws.metrics_stream import WebSocketManager

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

# Shared WebSocket manager — initialized in main.py lifespan
ws_manager = WebSocketManager()


@router.get("/{service_name}", response_model=MetricsSnapshot)
async def get_metrics(service_name: str, state: DashboardState = Depends(get_state)):
    cached = state.metrics_cache.get(service_name)
    if cached:
        return cached
    return MetricsSnapshot(service_name=service_name, status="unknown")


@router.websocket("/ws")
async def websocket_metrics(ws: WebSocket, state: DashboardState = Depends(get_state)):
    await ws_manager.connect(ws)
    try:
        # Send initial snapshot
        await ws.send_json({
            "type": "initial",
            "services": {
                name: snap.model_dump()
                for name, snap in state.metrics_cache.items()
            },
        })
        # Keep alive — listen for client messages
        while True:
            data = await ws.receive_text()
            # Client can send subscribe/filter messages (future use)
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
