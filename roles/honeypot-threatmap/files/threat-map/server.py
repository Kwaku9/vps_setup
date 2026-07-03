"""
Threat map backend — streams honeypot + CrowdSec + Traefik events via WebSocket.
Queries Loki for live events and serves the static frontend.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

LOKI_URL      = os.environ.get("LOKI_URL",      "http://logs-pod:3100")
LOKI_ORG      = os.environ.get("LOKI_ORG",      "enterprise")
POLL_SECS     = float(os.environ.get("POLL_SECS", "4"))
CROWDSEC_URL  = os.environ.get("CROWDSEC_URL",  "http://security-infra-pod:8180")
CROWDSEC_KEY  = os.environ.get("CROWDSEC_KEY",  "")
GEOIP_DB_PATH = os.environ.get("GEOIP_DB",      "/geoip/GeoLite2-City.mmdb")

# VPS target coords (for attack arc destination)
TARGET_LAT = float(os.environ.get("TARGET_LAT", "40.7128"))
TARGET_LON = float(os.environ.get("TARGET_LON", "-74.0060"))

# ---------------------------------------------------------------------------
# Local MaxMind GeoIP (shared with honeypot)
# ---------------------------------------------------------------------------
_mmdb = None

def _load_mmdb():
    global _mmdb
    try:
        import maxminddb
        _mmdb = maxminddb.open_database(GEOIP_DB_PATH)
    except Exception as e:
        pass  # GeoIP unavailable, CrowdSec bans won't have coordinates

def geoip_local(ip: str) -> dict:
    """Look up an IP in the local MaxMind DB. Returns empty coords on failure."""
    if not _mmdb:
        return {"country": "Unknown", "country_code": "??", "city": "", "lat": 0.0, "lon": 0.0}
    try:
        rec = _mmdb.get(ip)
        if rec:
            country = rec.get("country", {})
            city    = rec.get("city", {})
            loc     = rec.get("location", {})
            return {
                "country":      country.get("names", {}).get("en", "Unknown"),
                "country_code": country.get("iso_code", "??"),
                "city":         city.get("names", {}).get("en", ""),
                "lat":          loc.get("latitude", 0.0),
                "lon":          loc.get("longitude", 0.0),
            }
    except Exception:
        pass
    return {"country": "Unknown", "country_code": "??", "city": "", "lat": 0.0, "lon": 0.0}

_load_mmdb()

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws) if hasattr(self.active, "discard") else None
        try:
            self.active.remove(ws)
        except ValueError:
            pass

    async def broadcast(self, msg: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()

# ---------------------------------------------------------------------------
# Loki query helpers
# ---------------------------------------------------------------------------
async def loki_query_range(query: str, start_ns: int, end_ns: int, limit: int = 100) -> list[dict]:
    """Return list of parsed log entries from Loki."""
    params = {
        "query": query,
        "start": str(start_ns),
        "end":   str(end_ns),
        "limit": str(limit),
        "direction": "forward",
    }
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                f"{LOKI_URL}/loki/api/v1/query_range",
                params=params,
                headers={"X-Scope-OrgID": LOKI_ORG},
            )
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:
        return []

    events = []
    for stream in data.get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for ts_ns, line in stream.get("values", []):
            try:
                parsed = json.loads(line)
                parsed["_loki_labels"] = labels
                parsed["_ts_ns"] = int(ts_ns)
                events.append(parsed)
            except Exception:
                pass
    return sorted(events, key=lambda e: e["_ts_ns"])

def _ns_ago(seconds: float) -> int:
    return int((time.time() - seconds) * 1e9)

def _now_ns() -> int:
    return int(time.time() * 1e9)

# ---------------------------------------------------------------------------
# Event normalizers
# ---------------------------------------------------------------------------
def normalize_honeypot(e: dict) -> dict | None:
    if not e.get("honeypot"):
        return None
    lat, lon = e.get("lat", 0.0), e.get("lon", 0.0)
    if lat == 0.0 and lon == 0.0:
        return None
    return {
        "type":         "honeypot",
        "ts":           e.get("timestamp", ""),
        "ip":           e.get("ip", ""),
        "country":      e.get("country", "Unknown"),
        "country_code": e.get("country_code", "??"),
        "city":         e.get("city", ""),
        "lat":          lat,
        "lon":          lon,
        "path":         e.get("path", "/"),
        "method":       e.get("method", "GET"),
        "attack_type":  e.get("attack_type", "probe"),
        "user_agent":   e.get("user_agent", "")[:120],
        "target_lat":   TARGET_LAT,
        "target_lon":   TARGET_LON,
    }

def normalize_crowdsec(e: dict, labels: dict) -> dict | None:
    # CrowdSec ban decisions look like: "time=... level=info msg="... ban ..."
    msg = e.get("msg", "") or str(e)
    if "ban" not in msg.lower() and "decision" not in msg.lower():
        return None
    return {
        "type":        "crowdsec_ban",
        "ts":          e.get("time", ""),
        "msg":         msg[:200],
        "attack_type": "banned",
    }

# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------
_country_cache: dict[str, int] = {}
_path_cache:    dict[str, int] = {}
_type_cache:    dict[str, int] = {}

@app.get("/api/stats")
async def stats():
    start = _ns_ago(86400)  # last 24h
    end   = _now_ns()

    events = await loki_query_range(
        '{container_name="honeypot"} | json | honeypot="true"',
        start, end, limit=2000
    )

    countries: dict[str, int] = {}
    paths:     dict[str, int] = {}
    types:     dict[str, int] = {}
    total = 0

    for e in events:
        total += 1
        cc = e.get("country", "Unknown")
        countries[cc] = countries.get(cc, 0) + 1
        path = e.get("path", "/")[:40]
        paths[path] = paths.get(path, 0) + 1
        at = e.get("attack_type", "probe")
        types[at] = types.get(at, 0) + 1

    top_countries = sorted(countries.items(), key=lambda x: -x[1])[:10]
    top_paths     = sorted(paths.items(),     key=lambda x: -x[1])[:10]
    top_types     = sorted(types.items(),     key=lambda x: -x[1])[:8]

    return {
        "total_24h":     total,
        "top_countries": [{"country": k, "count": v} for k, v in top_countries],
        "top_paths":     [{"path": k,    "count": v} for k, v in top_paths],
        "attack_types":  [{"type": k,    "count": v} for k, v in top_types],
    }

@app.get("/api/recent")
async def recent():
    """Last 50 honeypot events (for initial page load)."""
    start = _ns_ago(3600)
    end   = _now_ns()
    events = await loki_query_range(
        '{container_name="honeypot"} | json | honeypot="true"',
        start, end, limit=50
    )
    normalized = [normalize_honeypot(e) for e in reversed(events)]
    return [e for e in normalized if e]

# ---------------------------------------------------------------------------
# Background poller → WebSocket broadcast
# ---------------------------------------------------------------------------
_last_ts_ns: int = 0

async def poll_loop():
    global _last_ts_ns
    _last_ts_ns = _ns_ago(30)

    while True:
        await asyncio.sleep(POLL_SECS)
        if not manager.active:
            continue

        end = _now_ns()
        start = _last_ts_ns

        # Honeypot events
        hp_events = await loki_query_range(
            '{container_name="honeypot"} | json | honeypot="true"',
            start, end, limit=20
        )
        for e in hp_events:
            n = normalize_honeypot(e)
            if n:
                await manager.broadcast({"event": "attack", "data": n})
            _last_ts_ns = max(_last_ts_ns, e["_ts_ns"] + 1)

        # CrowdSec bans — poll LAPI directly for new decisions
        if CROWDSEC_KEY:
            try:
                async with httpx.AsyncClient(timeout=5) as cs:
                    r = await cs.get(
                        f"{CROWDSEC_URL}/v1/decisions/stream",
                        params={"startup": "false"},
                        headers={"X-Api-Key": CROWDSEC_KEY},
                    )
                    if r.status_code == 200:
                        data = r.json() or {}
                        new_decisions = data.get("new", []) or []
                        for dec in new_decisions[:20]:
                            ip = dec.get("value", "")
                            if not ip or ":" in ip:  # skip IPv6 for now
                                continue
                            geo = geoip_local(ip)
                            if geo["lat"] == 0.0 and geo["lon"] == 0.0:
                                continue
                            ban_event = {
                                "type":         "crowdsec_ban",
                                "ts":           dec.get("start_ip", ""),
                                "ip":           ip,
                                "country":      geo["country"],
                                "country_code": geo["country_code"],
                                "city":         geo["city"],
                                "lat":          geo["lat"],
                                "lon":          geo["lon"],
                                "attack_type":  "banned",
                                "path":         f"Banned: {dec.get('scenario', 'threat')}",
                                "method":       "BAN",
                                "user_agent":   dec.get("scenario", ""),
                                "target_lat":   TARGET_LAT,
                                "target_lon":   TARGET_LON,
                            }
                            await manager.broadcast({"event": "ban", "data": ban_event})
            except Exception:
                pass

        if not hp_events:
            _last_ts_ns = end

@app.on_event("startup")
async def startup():
    asyncio.create_task(poll_loop())

# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)

# ---------------------------------------------------------------------------
# Static files + index
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory="/app/static"), name="static")

@app.get("/")
async def index():
    return FileResponse("/app/static/index.html")

@app.get("/health")
async def health():
    return {"status": "ok"}
