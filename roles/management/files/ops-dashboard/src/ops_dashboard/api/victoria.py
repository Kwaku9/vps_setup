"""Victoria Metrics HTTP API client for querying container metrics."""

import os
import time

import httpx

from .schemas import MetricsSnapshot


# Map container names (podman) -> service names (profiles.yaml)
CONTAINER_TO_SERVICE = {
    "postgres": "shared-db",
    "victoriametrics": "victoria-metrics",
    "ai-stack-postgres": "ai-stack-postgres",
}


class VictoriaMetricsClient:
    """Queries Victoria Metrics for container CPU/memory metrics."""

    def __init__(self, base_url: str | None = None):
        base_url = base_url or os.environ.get("VM_URL", "http://metrics-pod:8428")
        self.base_url = base_url
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def query(self, promql: str) -> list[dict]:
        client = await self._get_client()
        resp = await client.get("/api/v1/query", params={"query": promql})
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("result", [])

    async def query_all_containers(self) -> dict[str, MetricsSnapshot]:
        """Batch query all container metrics — CPU, memory, state."""
        now = time.time()
        snapshots: dict[str, MetricsSnapshot] = {}

        def _map_name(container_name: str) -> str:
            return CONTAINER_TO_SERVICE.get(container_name, container_name)

        # Query container states
        try:
            state_results = await self.query("podman_container_state")
            for r in state_results:
                raw_name = r["metric"].get("name", "")
                if not raw_name:
                    continue
                name = _map_name(raw_name)
                state_val = int(float(r["value"][1]))
                status = {2: "running", 3: "stopped", 4: "paused", 5: "exited"}.get(state_val, "unknown")
                snapshots[name] = MetricsSnapshot(
                    service_name=name,
                    timestamp=now,
                    status=status,
                )
        except Exception:
            pass

        # Query CPU percent
        try:
            cpu_results = await self.query("podman_container_cpu_percent")
            for r in cpu_results:
                name = _map_name(r["metric"].get("name", ""))
                cpu = float(r["value"][1])
                if name in snapshots:
                    snapshots[name].cpu_percent = cpu
        except Exception:
            pass

        # Query memory percent
        try:
            mem_results = await self.query("podman_container_mem_percent")
            for r in mem_results:
                name = _map_name(r["metric"].get("name", ""))
                mem = float(r["value"][1])
                if name in snapshots:
                    snapshots[name].memory_percent = mem
        except Exception:
            pass

        # Query memory usage bytes
        try:
            mem_bytes_results = await self.query("podman_container_mem_usage_bytes")
            for r in mem_bytes_results:
                name = _map_name(r["metric"].get("name", ""))
                mem_bytes = float(r["value"][1])
                if name in snapshots:
                    snapshots[name].memory_usage_mb = round(mem_bytes / 1048576, 1)
        except Exception:
            pass

        return snapshots
