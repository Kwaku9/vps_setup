"""Metrics REST fallback and WebSocket endpoint."""

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from ..dependencies import DashboardState, get_state
from ..schemas import MetricsSnapshot
from ..victoria import VictoriaMetricsClient
from ..ws.metrics_stream import WebSocketManager

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

# Shared WebSocket manager — initialized in main.py lifespan
ws_manager = WebSocketManager()

# One client per process — cheap to construct, expensive to leak
_vm = VictoriaMetricsClient()

_METRIC_TO_PROMQL = {
    "cpu": 'podman_container_cpu_percent{{name="{name}"}}',
    "mem": '100 * podman_container_mem_usage_bytes{{name="{name}"}} '
           '/ ignoring(__name__) podman_container_mem_limit_bytes{{name="{name}"}}',
}


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


@router.get("/{service_name}/timeseries")
async def get_timeseries(service_name: str, metric: str = "cpu", minutes: int = 15):
    if metric not in _METRIC_TO_PROMQL:
        raise HTTPException(400, f"metric must be one of {list(_METRIC_TO_PROMQL)}")
    if not 1 <= minutes <= 240:
        raise HTTPException(400, "minutes must be between 1 and 240")
    promql = _METRIC_TO_PROMQL[metric].format(name=service_name)
    points = await _vm.query_range(promql, minutes=minutes)
    return {"service_name": service_name, "metric": metric, "minutes": minutes, "points": points}
