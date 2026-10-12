"""Triage: the live state the phone app's home screen opens on.

One read-only call for what can change minute to minute: alerts vmalert holds
right now (the graph's AlertRule.state is only refreshed nightly), host load,
memory and disk, the backup's age and failing cron jobs. Approvals, sessions,
containers and inventory findings come from their own routers.
"""
from __future__ import annotations

import asyncio
import os

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/triage", tags=["triage"])

VM_URL = os.environ.get("VM_URL", "http://metrics-pod:8428")
VMALERT_URL = os.environ.get("VMALERT_URL", "http://metrics-pod:8880")

HOST_QUERIES = {
    "load1": "max(node_load1)",
    "cpus": 'count(count by (cpu) (node_cpu_seconds_total{mode="idle"}))',
    "mem_used": "1 - max(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)",
    "swap_used": "1 - max(node_memory_SwapFree_bytes / node_memory_SwapTotal_bytes)",
    "disk_used": '1 - max(node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})',
    "backup_age_s": "max(vps_backup_last_success_age_seconds)",
}


async def _vm_scalar(c: httpx.AsyncClient, promql: str) -> float | None:
    try:
        r = await c.get(f"{VM_URL}/api/v1/query", params={"query": promql})
        r.raise_for_status()
        res = r.json()["data"]["result"]
        return float(res[0]["value"][1]) if res else None
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return None


def shape_alerts(raw: list[dict]) -> list[dict]:
    """vmalert's /api/v1/alerts entries -> what a triage card needs, firing first."""
    out = []
    for a in raw:
        labels, ann = a.get("labels") or {}, a.get("annotations") or {}
        out.append({
            "name": a.get("name") or labels.get("alertname"),
            "state": a.get("state"),
            "severity": labels.get("severity", "warning"),
            "since": a.get("activeAt"),
            "summary": ann.get("summary"),
            "description": ann.get("description"),
            "target": labels.get("cron_job") or labels.get("container_name") or labels.get("name")
                      or labels.get("mountpoint"),
        })
    rank = {"firing": 0, "pending": 1}
    return sorted(out, key=lambda x: (rank.get(x["state"], 2), x["severity"] != "critical", x["since"] or ""))


@router.get("")
async def triage():
    async with httpx.AsyncClient(timeout=6) as c:
        async def alerts():
            try:
                r = await c.get(f"{VMALERT_URL}/api/v1/alerts")
                r.raise_for_status()
                return shape_alerts(r.json()["data"]["alerts"]), None
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                return [], f"vmalert unreachable ({type(exc).__name__})"

        async def failing():
            try:
                r = await c.get(f"{VM_URL}/api/v1/query", params={"query": "cron_job_last_exit_code != 0"})
                r.raise_for_status()
                return sorted({x["metric"].get("cron_job") for x in r.json()["data"]["result"]} - {None})
            except (httpx.HTTPError, KeyError, ValueError):
                return []

        names = list(HOST_QUERIES)
        results = await asyncio.gather(alerts(), failing(), *(_vm_scalar(c, HOST_QUERIES[n]) for n in names))
    (alert_list, alert_error), failing_jobs, *values = results
    host = dict(zip(names, values))
    backup_age = host.pop("backup_age_s")
    return {"alerts": alert_list, "alerts_error": alert_error, "host": host,
            "backup_age_s": backup_age, "failing_jobs": failing_jobs}
