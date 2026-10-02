"""Repo Radar: git state of every repository in a workspace, per host.

Two feeds land in `sessions.repo_radar_snapshots` (one row per host):

* laptop  — repo-radar/push.sh on the workstation POSTs the local radar's
            /api/state here (over ssh to the VPS loopback, bearer = the same
            SESSION_INGEST_TOKEN the session hooks use).
* vps     — this process runs `node scan.mjs --json <root>` over the existing
            SSH provider every REPO_RADAR_VPS_INTERVAL seconds against the VPS's
            own repo copies, so drift between the two working trees is visible
            side by side.

The snapshot shape is exactly repo-radar's state object (repos, prs, prError,
scannedAt, scanMs, root) plus `host`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from fastapi import APIRouter, Header, HTTPException, Request

from ...providers.vps import VpsProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/repo-radar", tags=["repo-radar"])

# In-memory mirror of the table so GET /state never needs the DB on the hot path
# and still answers (from the last good value) while the pool is down.
_cache: dict[str, dict] = {}


def _check_token(authorization: str | None):
    expected = os.environ.get("SESSION_INGEST_TOKEN", "")
    if not expected or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="invalid ingest token")


def _safe_prs(prs) -> dict:
    """Keep only PRs whose link is a real GitHub https URL.

    The UI renders pr.url straight into <a href>, so a `javascript:` (or any
    non-https) URL in a pushed snapshot would execute in the operator's
    browser. GitHub only ever returns https://github.com/... links, so anything
    else is either corruption or an attack and is dropped rather than rendered.
    """
    out: dict = {}
    if not isinstance(prs, dict):
        return out
    for repo, items in prs.items():
        if not isinstance(items, list):
            continue
        out[repo] = [p for p in items
                     if isinstance(p, dict) and isinstance(p.get("url"), str)
                     and p["url"].startswith("https://github.com/")]
    return out


def _sanitize(snapshot: dict, host: str) -> dict:
    """Keep only the fields the UI needs; drop absolute paths of other hosts'
    working trees except the root, which is what the radar shows as its title."""
    repos = []
    for r in snapshot.get("repos") or []:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        repos.append({k: v for k, v in r.items() if k != "dir"})
    return {
        "host": host,
        "root": snapshot.get("root"),
        "scannedAt": snapshot.get("scannedAt"),
        "scanMs": snapshot.get("scanMs"),
        "repos": repos,
        "prs": _safe_prs(snapshot.get("prs")),
        "prError": snapshot.get("prError"),
        "fatal": snapshot.get("fatal"),
    }


async def store_snapshot(pool, host: str, snapshot: dict) -> None:
    snap = _sanitize(snapshot, host)
    snap["receivedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _cache[host] = snap
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO sessions.repo_radar_snapshots (host, payload, received_at)
               VALUES ($1, $2::jsonb, now())
               ON CONFLICT (host) DO UPDATE SET payload = EXCLUDED.payload, received_at = now()""",
            host, json.dumps(snap),
        )


async def load_snapshots(pool) -> dict[str, dict]:
    if pool is None:
        return dict(_cache)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT host, payload, received_at FROM sessions.repo_radar_snapshots")
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload["receivedAt"] = r["received_at"].isoformat()
        _cache[r["host"]] = payload
    return dict(_cache)


@router.post("/ingest")
async def ingest(request: Request, authorization: str | None = Header(default=None)):
    _check_token(authorization)
    body = await request.json()
    host = str(body.get("host") or "laptop")[:40]
    if not isinstance(body.get("repos"), list):
        raise HTTPException(status_code=422, detail="repos[] required")
    await store_snapshot(request.app.state.db_pool, host, body)
    return {"ok": True, "host": host, "repos": len(body["repos"])}


@router.get("/state")
async def state(request: Request):
    hosts = await load_snapshots(request.app.state.db_pool)
    return {"hosts": hosts, "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


# ── VPS self-scan ──────────────────────────────────────────────────────────
VPS_ROOT = os.environ.get("REPO_RADAR_VPS_ROOT", "")
VPS_SCANNER = os.environ.get("REPO_RADAR_VPS_SCANNER", "/opt/repo-radar/scan.mjs")
VPS_INTERVAL = int(os.environ.get("REPO_RADAR_VPS_INTERVAL", "300"))


async def scan_vps_once(pool) -> bool:
    provider = VpsProvider()
    out, rc = await provider._ssh_command(
        f"node {VPS_SCANNER} --json {VPS_ROOT}", timeout=120,
    )
    if rc != 0 or not out:
        logger.warning("repo-radar vps scan failed (rc=%s)", rc)
        return False
    try:
        snapshot = json.loads(out)
    except json.JSONDecodeError:
        logger.warning("repo-radar vps scan returned non-JSON output")
        return False
    await store_snapshot(pool, "vps", snapshot)
    return True


async def vps_scan_loop(app) -> None:
    if not VPS_ROOT:
        logger.info("repo-radar: REPO_RADAR_VPS_ROOT unset, VPS self-scan disabled")
        return
    await asyncio.sleep(15)  # let the pool + SSH known_hosts settle after boot
    while True:
        try:
            await scan_vps_once(getattr(app.state, "db_pool", None))
        except Exception as exc:  # noqa: BLE001 — a failed sweep must not end the loop
            logger.warning("repo-radar vps scan error: %s", exc)
        await asyncio.sleep(VPS_INTERVAL)


@router.post("/rescan")
async def rescan(request: Request):
    if not VPS_ROOT:
        raise HTTPException(status_code=404, detail="VPS self-scan disabled")
    ok = await scan_vps_once(request.app.state.db_pool)
    return {"ok": ok, "host": "vps"}
