"""WebSocket manager for real-time metrics streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import WebSocket

from ..victoria import VictoriaMetricsClient

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and broadcasts metrics updates."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)
        logger.info(f"WS client connected ({len(self.active_connections)} total)")

    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections:
            self.active_connections.remove(ws)
        logger.info(f"WS client disconnected ({len(self.active_connections)} total)")

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


HOST_SERVICES = ["fail2ban", "squid", "node-exporter", "iptables", "crond"]


async def poll_host_services(ssh_host: str = "localhost", ssh_user: str = "root") -> dict:
    """Query host service status via SSH + rc-service."""
    from ..schemas import MetricsSnapshot
    snapshots = {}
    try:
        cmd = " && ".join(
            f'echo "{svc}:$(rc-service {svc} status 2>&1 | grep -o "started\\|stopped\\|crashed")"'
            for svc in HOST_SERVICES
        )
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-o", "ConnectTimeout=5", f"{ssh_user}@{ssh_host}", cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        now = time.time()
        for line in stdout.decode().strip().split("\n"):
            if ":" not in line:
                continue
            name, status_str = line.split(":", 1)
            name = name.strip()
            status = "running" if status_str.strip() == "started" else "stopped"
            snapshots[name] = MetricsSnapshot(
                service_name=name,
                timestamp=now,
                cpu_percent=0.0,
                memory_percent=0.0,
                memory_usage_mb=0.0,
                status=status,
            )
    except Exception as e:
        logger.warning(f"Host service poll error: {e}")
    return snapshots


async def metrics_poll_loop(
    ws_manager: WebSocketManager,
    vm_client: VictoriaMetricsClient,
    metrics_cache: dict,
    interval: float = 5.0,
):
    """Background task: polls Victoria Metrics + host services and broadcasts to all WS clients."""
    host_poll_counter = 0
    while True:
        try:
            # Always poll VM for container metrics
            snapshots = await vm_client.query_all_containers()
            metrics_cache.update(snapshots)

            # Poll host services every 6th cycle (~30s)
            host_poll_counter += 1
            if host_poll_counter >= 6:
                host_poll_counter = 0
                import os
                ssh_host = os.environ.get("SSH_HOST", "localhost")
                host_snapshots = await poll_host_services(ssh_host=ssh_host)
                metrics_cache.update(host_snapshots)
                snapshots.update(host_snapshots)

            if ws_manager.active_connections:
                await ws_manager.broadcast({
                    "type": "metrics_update",
                    "timestamp": time.time(),
                    "services": {
                        name: snap.model_dump()
                        for name, snap in snapshots.items()
                    },
                })
        except Exception as e:
            logger.warning(f"Metrics poll error: {e}")
        await asyncio.sleep(interval)
