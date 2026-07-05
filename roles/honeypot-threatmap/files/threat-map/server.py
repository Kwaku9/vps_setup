"""
Threat map backend — streams honeypot + CrowdSec + Traefik events via WebSocket.

Sources
  honeypot      : Loki  {container_name="honeypot"}            (apex decoy hits)
  crowdsec_ban  : LAPI  /v1/decisions/stream (live, local origins only)
                  VM    cs_lapi_decision      (history — see VM_BAN_SELECTOR)
  traefik_probe : Loki  {job="traefik_access"} 4xx/429 on real subdomains

Also serves the static frontend, a clamped /api/history + /api/histogram for the
timeline scrubber, and /api/report which proxies panel renders to the
grafana-reports engine (bearer stays server-side).
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import time
from collections import OrderedDict
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

LOKI_URL      = os.environ.get("LOKI_URL",      "http://logs-pod:3100")
LOKI_ORG      = os.environ.get("LOKI_ORG",      "enterprise")
POLL_SECS     = float(os.environ.get("POLL_SECS", "4"))
CROWDSEC_URL  = os.environ.get("CROWDSEC_URL",  "http://security-infra-pod:8180")
CROWDSEC_KEY  = os.environ.get("CROWDSEC_KEY",  "")
GEOIP_DB_PATH = os.environ.get("GEOIP_DB",      "/geoip/GeoLite2-City.mmdb")
VM_URL        = os.environ.get("VM_URL",        "http://metrics-pod:8428")
REPORTS_URL   = os.environ.get("REPORTS_URL",   "http://reports-pod:8765")
REPORTS_TOKEN = os.environ.get("REPORTS_TOKEN", "")
# Browsers always send Origin on cross-site WS; empty Origin (curl, native) passes
# because auth lives at the Cloudflare Access edge, not here.
WS_ORIGINS    = {o.strip() for o in os.environ.get(
    "ALLOWED_WS_ORIGINS", "https://threat.aicortex.cloud").split(",") if o.strip()}

# VPS target coords (attack arc destination)
TARGET_LAT = float(os.environ.get("TARGET_LAT", "40.7128"))
TARGET_LON = float(os.environ.get("TARGET_LON", "-74.0060"))

LOKI_RETENTION_DAYS = 14      # loki-config.yml.j2 retention_period 336h
VM_RETENTION_DAYS   = 60      # monitoring defaults retention "60"
MAX_HISTORY_DAYS    = 90
MAX_HISTORY_LIMIT   = 4000
MAX_HISTO_BUCKETS   = 300

# cs_lapi_decision is written by TWO producers: the CrowdSec http notifier (real
# local decisions) and the crowdsec-geo-feed cron (CAPI community-blocklist
# *sampler* — decorative, NOT attacks on us). New samples carry an `origin`
# label; legacy samples are told apart by asnumber shape (geo-feed wrote
# "AS15169", the notifier writes bare numbers).
VM_BAN_SELECTOR = '{__name__="cs_lapi_decision",asnumber!~"AS.+",origin!="capi"}'
# Live LAPI stream: only locally-triggered decision origins count as attacks.
LOCAL_DECISION_ORIGINS = {"crowdsec", "cscli", "appsec"}

LOKI_HONEYPOT_QUERY = '{container_name="honeypot"} | json | honeypot="true"'
LOKI_PROBE_SELECTOR = ('{job="traefik_access", downstream_status=~"40[0-9]|429", '
                       'router_name!~"apex-honeypot.*|threat-map.*"}')
LOKI_PROBE_QUERY = LOKI_PROBE_SELECTOR + " | json"

# Paths whose 4xx are everyday browser noise, not probes.
BENIGN_PROBE_PATHS = {"/favicon.ico", "/robots.txt", "/apple-touch-icon.png",
                      "/apple-touch-icon-precomposed.png"}
BENIGN_PROBE_PREFIXES = ("/.well-known/",)

# ---------------------------------------------------------------------------
# Attack classification (taxonomy mirrors honeypot.py — keep the two in sync)
# ---------------------------------------------------------------------------
_PATH_RULES: list[tuple[str, list[str]]] = [
    ("wordpress_probe",  ["/wp-login", "/wp-admin", "/xmlrpc.php", "/wp-content", "/wp-includes"]),
    ("env_probe",        ["/.env", "/.env.", "/config.php", "/configuration.php", "/settings.php", "/local.php"]),
    ("git_probe",        ["/.git/", "/.svn/", "/.hg/"]),
    ("db_probe",         ["/phpmyadmin", "/pma", "/adminer", "/mysql", "/myadmin"]),
    ("admin_probe",      ["/admin", "/administrator", "/manager", "/dashboard", "/panel", "/console", "/control"]),
    ("api_probe",        ["/api/", "/graphql", "/swagger", "/openapi", "/v1/", "/v2/"]),
    ("shell_probe",      ["/shell", "/cmd", "/exec", "/eval", "/cgi-bin", "/bin/sh"]),
    ("backup_probe",     [".bak", ".backup", ".old", ".sql", ".zip", ".tar"]),
    ("path_traversal",   ["../", "%2e%2e", "%252e"]),
    ("credential_probe", ["/login", "/signin", "/auth", "/account", "/user", "/password"]),
    ("cms_probe",        ["/joomla", "/drupal", "/magento", "/typo3", "/moodle", "/prestashop"]),
]

def classify(path: str) -> str:
    lp = (path or "").lower()
    for attack_type, patterns in _PATH_RULES:
        if any(p in lp for p in patterns):
            return attack_type
    return "generic_probe"

# ---------------------------------------------------------------------------
# Local MaxMind GeoIP (shared with honeypot)
# ---------------------------------------------------------------------------
_mmdb = None

def _load_mmdb():
    global _mmdb
    try:
        import maxminddb
        _mmdb = maxminddb.open_database(GEOIP_DB_PATH)
    except Exception:
        pass  # GeoIP unavailable — events degrade to geo_ok=False

def geoip_local(ip: str) -> dict:
    """Look up an IP (v4 or v6) in the local MaxMind DB."""
    unknown = {"country": "Unknown", "country_code": "??", "city": "", "lat": 0.0, "lon": 0.0}
    if not _mmdb:
        return unknown
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
                "lat":          loc.get("latitude", 0.0) or 0.0,
                "lon":          loc.get("longitude", 0.0) or 0.0,
            }
    except Exception:
        pass
    return unknown

def _is_private_ip(ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
        return parsed.is_private or parsed.is_loopback or parsed.is_link_local
    except ValueError:
        return True  # unparseable → treat as internal noise

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
# Event normalizers (pure — unit-tested in tests/test_server.py)
# ---------------------------------------------------------------------------
def _base_event(etype: str, ts_ms: int, geo: dict) -> dict:
    lat = float(geo.get("lat") or 0.0)
    lon = float(geo.get("lon") or 0.0)
    return {
        "type":         etype,
        "ts_ms":        int(ts_ms),
        "ip":           "",
        "country":      geo.get("country", "Unknown"),
        "country_code": geo.get("country_code", "??"),
        "city":         geo.get("city", ""),
        "lat":          lat,
        "lon":          lon,
        "geo_ok":       bool(lat or lon),
        "target_lat":   TARGET_LAT,
        "target_lon":   TARGET_LON,
    }

def normalize_honeypot(e: dict) -> dict | None:
    """Honeypot JSON log line → event. Unknown geo is kept (geo_ok=False)."""
    if not e.get("honeypot"):
        return None
    ts_ms = e.get("_ts_ns", 0) // 1_000_000 or int(time.time() * 1000)
    evt = _base_event("honeypot", ts_ms, {
        "country": e.get("country", "Unknown"), "country_code": e.get("country_code", "??"),
        "city": e.get("city", ""), "lat": e.get("lat", 0.0), "lon": e.get("lon", 0.0),
    })
    evt.update({
        "ip":          e.get("ip", ""),
        "path":        e.get("path", "/"),
        "method":      e.get("method", "GET"),
        "attack_type": e.get("attack_type", "generic_probe"),
        "user_agent":  (e.get("user_agent") or "")[:120],
    })
    return evt

def normalize_decision(dec: dict, geo: dict, now_ms: int) -> dict | None:
    """CrowdSec LAPI decision → ban event. Community (CAPI) decisions are not
    attacks on this host — callers filter by LOCAL_DECISION_ORIGINS."""
    ip = dec.get("value", "")
    if not ip or dec.get("scope", "Ip") != "Ip":
        return None
    origin = (dec.get("origin") or "").lower()
    if origin not in LOCAL_DECISION_ORIGINS:
        return None
    evt = _base_event("crowdsec_ban", now_ms, geo)
    scenario = dec.get("scenario", "threat")
    evt.update({
        "ip":          ip,
        "path":        f"Banned: {scenario}",
        "method":      "BAN",
        "attack_type": "banned",
        "user_agent":  scenario,
        "origin":      origin,
        "duration":    dec.get("duration", ""),
    })
    return evt

def normalize_traefik(e: dict) -> dict | None:
    """Traefik access-log JSON line (4xx/429 on real subdomains) → probe event.
    Real client IP: Cf-Connecting-Ip → first XFF hop → ClientAddr. Internal
    traffic without CF headers and benign browser noise are dropped."""
    path = e.get("RequestPath", "") or ""
    bare = path.split("?", 1)[0]
    if bare in BENIGN_PROBE_PATHS or bare.startswith(BENIGN_PROBE_PREFIXES):
        return None

    ip = (e.get("request_Cf-Connecting-Ip") or "").strip()
    from_cf = bool(ip)
    if not ip:
        xff = (e.get("request_X-Forwarded-For") or "").split(",")[0].strip()
        ip = xff
    if not ip:
        ip = (e.get("ClientAddr") or "").rsplit(":", 1)[0].strip("[]")
    if not ip or (not from_cf and _is_private_ip(ip)):
        return None  # internal noise (health probes, pod-to-pod)

    try:
        status = int(e.get("DownstreamStatus", 0))
    except (TypeError, ValueError):
        status = 0
    if status == 401:
        attack_type = "auth_failure"
    elif status == 403:
        attack_type = "access_denied"
    elif status == 429:
        attack_type = "rate_limited"
    else:
        attack_type = classify(path)

    geo = geoip_local(ip)
    if geo["country_code"] in ("??", "XX"):
        cf_country = (e.get("request_Cf-Ipcountry") or "").upper()
        if len(cf_country) == 2 and cf_country not in ("XX", "T1"):
            geo = dict(geo, country_code=cf_country, country=cf_country)

    ts_ms = e.get("_ts_ns", 0) // 1_000_000 or int(time.time() * 1000)
    evt = _base_event("traefik_probe", ts_ms, geo)
    evt.update({
        "ip":          ip,
        "path":        path[:120],
        "method":      e.get("RequestMethod", "GET"),
        "attack_type": attack_type,
        "user_agent":  (e.get("request_User-Agent") or "")[:120],
        "host":        e.get("RequestHost", ""),
        "status":      status,
    })
    return evt

def vm_line_to_events(line: dict) -> list[dict]:
    """One VM /api/v1/export JSON line (a series) → one ban event per sample."""
    labels = line.get("metric", {})
    try:
        lat = float(labels.get("latitude") or 0.0)
        lon = float(labels.get("longitude") or 0.0)
    except (TypeError, ValueError):
        lat = lon = 0.0
    cc = (labels.get("country") or "??")[:2].upper() or "??"
    events = []
    for ts_ms in line.get("timestamps", []):
        evt = _base_event("crowdsec_ban", ts_ms, {
            "country": cc, "country_code": cc, "city": "", "lat": lat, "lon": lon,
        })
        scenario = labels.get("scenario", "threat")
        evt.update({
            "ip":          labels.get("ip", ""),
            "path":        f"Banned: {scenario}",
            "method":      "BAN",
            "attack_type": "banned",
            "user_agent":  scenario,
            "origin":      labels.get("origin", ""),
        })
        events.append(evt)
    return events

def clamp_range(start_ms: Any, end_ms: Any, now_ms: int,
                max_days: int = MAX_HISTORY_DAYS) -> tuple[int, int]:
    """Validate and clamp a [start, end] ms range. Raises ValueError."""
    try:
        start = int(start_ms)
        end = int(end_ms)
    except (TypeError, ValueError):
        raise ValueError("start/end must be epoch milliseconds")
    end = min(end, now_ms)
    floor = now_ms - max_days * 86_400_000
    start = max(start, floor)
    if start >= end:
        raise ValueError("start must be before end (after clamping)")
    return start, end

def downsample(events: list[dict], limit: int) -> tuple[list[dict], bool]:
    """Uniform-stride downsample preserving temporal distribution + last event."""
    n = len(events)
    if n <= limit:
        return events, False
    stride = -(-n // limit)  # ceil → len(events[::stride]) <= limit
    sampled = events[::stride][:limit]
    if sampled[-1] is not events[-1]:
        sampled[-1] = events[-1]  # keep the newest event without exceeding limit
    return sampled, True

# ---------------------------------------------------------------------------
# Loki / VictoriaMetrics query helpers
# ---------------------------------------------------------------------------
async def loki_query_range(query: str, start_ns: int, end_ns: int,
                           limit: int = 100) -> list[dict] | None:
    """Parsed log entries from Loki, oldest-first. None = query failed
    (callers keep their cursor instead of skipping the window)."""
    params = {
        "query": query,
        "start": str(start_ns),
        "end":   str(end_ns),
        "limit": str(limit),
        "direction": "forward",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{LOKI_URL}/loki/api/v1/query_range",
                params=params,
                headers={"X-Scope-OrgID": LOKI_ORG},
            )
            if r.status_code != 200:
                return None
            data = r.json()
    except Exception:
        return None

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

async def loki_count_series(query: str, start_ms: int, end_ms: int,
                            step_s: int) -> dict[int, int]:
    """Metric query (count_over_time) → {bucket_epoch_ms: count}."""
    params = {
        "query": query,
        "start": str(start_ms * 1_000_000),
        "end":   str(end_ms * 1_000_000),
        "step":  f"{step_s}s",
    }
    out: dict[int, int] = {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{LOKI_URL}/loki/api/v1/query_range",
                params=params,
                headers={"X-Scope-OrgID": LOKI_ORG},
            )
            if r.status_code != 200:
                return out
            for series in r.json().get("data", {}).get("result", []):
                for ts_s, val in series.get("values", []):
                    bucket = int(float(ts_s)) * 1000
                    out[bucket] = out.get(bucket, 0) + int(float(val))
    except Exception:
        pass
    return out

async def vm_export_bans(start_ms: int, end_ms: int,
                         max_events: int = 5000) -> list[dict]:
    """Local ban events from VictoriaMetrics cs_lapi_decision, oldest-first."""
    params = {
        "match[]": VM_BAN_SELECTOR,
        "start": str(start_ms // 1000),
        "end":   str(-(-end_ms // 1000)),
    }
    events: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{VM_URL}/api/v1/export", params=params)
            if r.status_code != 200:
                return events
            for line in r.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.extend(vm_line_to_events(json.loads(line)))
                except Exception:
                    pass
    except Exception:
        return events
    events = [e for e in events if start_ms <= e["ts_ms"] <= end_ms]
    events.sort(key=lambda e: e["ts_ms"])
    return events[-max_events:]

async def vm_count_series(start_ms: int, end_ms: int, step_s: int) -> dict[int, int]:
    """Ban counts per bucket from VM query_range."""
    query = f"sum(count_over_time({VM_BAN_SELECTOR}[{step_s}s]))"
    params = {
        "query": query,
        "start": str(start_ms // 1000),
        "end":   str(-(-end_ms // 1000)),
        "step":  f"{step_s}s",
    }
    out: dict[int, int] = {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{VM_URL}/api/v1/query_range", params=params)
            if r.status_code != 200:
                return out
            for series in r.json().get("data", {}).get("result", []):
                for ts_s, val in series.get("values", []):
                    bucket = int(float(ts_s)) * 1000
                    out[bucket] = out.get(bucket, 0) + int(float(val))
    except Exception:
        pass
    return out

def _ns_ago(seconds: float) -> int:
    return int((time.time() - seconds) * 1e9)

def _now_ns() -> int:
    return int(time.time() * 1e9)

def _now_ms() -> int:
    return int(time.time() * 1000)

# ---------------------------------------------------------------------------
# Config + stats endpoints
# ---------------------------------------------------------------------------
@app.get("/api/config")
async def config():
    return {
        "target":  {"lat": TARGET_LAT, "lon": TARGET_LON},
        "sources": ["honeypot", "probes", "bans"],
        "retention_days": {"honeypot": LOKI_RETENTION_DAYS,
                           "probes": LOKI_RETENTION_DAYS,
                           "bans": VM_RETENTION_DAYS},
        "max_history_days": MAX_HISTORY_DAYS,
        "reports_enabled": bool(REPORTS_TOKEN),
        "now_ms": _now_ms(),
    }

_stats_cache: dict[str, Any] = {"ts": 0.0, "data": None}
_stats_lock = asyncio.Lock()

@app.get("/api/stats")
async def stats():
    async with _stats_lock:
        if _stats_cache["data"] and time.time() - _stats_cache["ts"] < 20:
            return _stats_cache["data"]

        now_ms = _now_ms()
        start_ns, end_ns = _ns_ago(86400), _now_ns()
        hp_raw, probe_raw, bans = await asyncio.gather(
            loki_query_range(LOKI_HONEYPOT_QUERY, start_ns, end_ns, limit=2000),
            loki_query_range(LOKI_PROBE_QUERY, start_ns, end_ns, limit=2000),
            vm_export_bans(now_ms - 86_400_000, now_ms),
        )
        events: list[dict] = list(bans)
        for raw, norm in ((hp_raw, normalize_honeypot), (probe_raw, normalize_traefik)):
            for e in raw or []:
                n = norm(e)
                if n:
                    events.append(n)

        countries: dict[tuple[str, str], int] = {}
        paths: dict[str, int] = {}
        types: dict[str, int] = {}
        by_source = {"honeypot": 0, "probes": 0, "bans": 0}
        rate_hour = 0
        hour_floor = now_ms - 3_600_000

        for e in events:
            key = (e.get("country", "Unknown"), e.get("country_code", "??"))
            countries[key] = countries.get(key, 0) + 1
            if e["type"] == "honeypot":
                by_source["honeypot"] += 1
                p = e.get("path", "/")[:40]
                paths[p] = paths.get(p, 0) + 1
            elif e["type"] == "traefik_probe":
                by_source["probes"] += 1
            else:
                by_source["bans"] += 1
            types[e.get("attack_type", "generic_probe")] = \
                types.get(e.get("attack_type", "generic_probe"), 0) + 1
            if e["ts_ms"] >= hour_floor:
                rate_hour += 1

        data = {
            "total_24h":   len(events),
            "rate_hour":   rate_hour,
            "by_source":   by_source,
            "top_countries": [
                {"country": k[0], "country_code": k[1], "count": v}
                for k, v in sorted(countries.items(), key=lambda x: -x[1])[:10]],
            "top_paths": [
                {"path": k, "count": v}
                for k, v in sorted(paths.items(), key=lambda x: -x[1])[:10]],
            "attack_types": [
                {"type": k, "count": v}
                for k, v in sorted(types.items(), key=lambda x: -x[1])[:8]],
        }
        _stats_cache.update(ts=time.time(), data=data)
        return data

@app.get("/api/recent")
async def recent(minutes: int = 60, limit: int = 50):
    """Recent events across all sources (initial page load), oldest-first."""
    minutes = max(1, min(int(minutes), 1440))
    limit = max(1, min(int(limit), 200))
    now_ms = _now_ms()
    start_ns, end_ns = _ns_ago(minutes * 60), _now_ns()

    hp_raw, probe_raw, bans = await asyncio.gather(
        loki_query_range(LOKI_HONEYPOT_QUERY, start_ns, end_ns, limit=limit),
        loki_query_range(LOKI_PROBE_QUERY, start_ns, end_ns, limit=limit),
        vm_export_bans(now_ms - minutes * 60_000, now_ms, max_events=limit),
    )
    events: list[dict] = list(bans)
    for raw, norm in ((hp_raw, normalize_honeypot), (probe_raw, normalize_traefik)):
        for e in raw or []:
            n = norm(e)
            if n:
                events.append(n)
    events.sort(key=lambda e: e["ts_ms"])
    return events[-limit:]

# ---------------------------------------------------------------------------
# History + histogram (timeline scrubber)
# ---------------------------------------------------------------------------
@app.get("/api/history")
async def history(start: str, end: str, limit: int = 1000, sources: str = ""):
    now_ms = _now_ms()
    try:
        start_ms, end_ms = clamp_range(start, end, now_ms)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    limit = max(10, min(int(limit), MAX_HISTORY_LIMIT))
    wanted = {s.strip() for s in sources.split(",") if s.strip()} or \
             {"honeypot", "probes", "bans"}

    loki_floor_ms = now_ms - LOKI_RETENTION_DAYS * 86_400_000
    loki_start_ms = max(start_ms, loki_floor_ms)
    per_source = min(limit, 3000)

    tasks = []
    if "honeypot" in wanted and loki_start_ms < end_ms:
        tasks.append(("honeypot", loki_query_range(
            LOKI_HONEYPOT_QUERY, loki_start_ms * 1_000_000,
            end_ms * 1_000_000, limit=per_source)))
    if "probes" in wanted and loki_start_ms < end_ms:
        tasks.append(("probes", loki_query_range(
            LOKI_PROBE_QUERY, loki_start_ms * 1_000_000,
            end_ms * 1_000_000, limit=per_source)))
    if "bans" in wanted:
        tasks.append(("bans", vm_export_bans(start_ms, end_ms, max_events=per_source)))

    results = await asyncio.gather(*(t[1] for t in tasks))
    events: list[dict] = []
    counts: dict[str, int] = {}
    for (name, _), res in zip(tasks, results):
        if name == "bans":
            counts[name] = len(res)
            events.extend(res)
        else:
            norm = normalize_honeypot if name == "honeypot" else normalize_traefik
            n_events = [n for n in (norm(e) for e in res or []) if n]
            counts[name] = len(n_events)
            events.extend(n_events)

    events.sort(key=lambda e: e["ts_ms"])
    events, truncated = downsample(events, limit)
    return {
        "events": events,
        "meta": {
            "start_ms": start_ms, "end_ms": end_ms, "counts": counts,
            "truncated": truncated,
            "loki_clipped": start_ms < loki_floor_ms,
        },
    }

@app.get("/api/histogram")
async def histogram(start: str, end: str, buckets: int = 120):
    now_ms = _now_ms()
    try:
        start_ms, end_ms = clamp_range(start, end, now_ms)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    buckets = max(10, min(int(buckets), MAX_HISTO_BUCKETS))
    step_s = max(1, (end_ms - start_ms) // buckets // 1000)

    loki_floor_ms = now_ms - LOKI_RETENTION_DAYS * 86_400_000
    loki_start_ms = max(start_ms, loki_floor_ms)

    hp_task = loki_count_series(
        f"sum(count_over_time({LOKI_HONEYPOT_QUERY} [{step_s}s]))",
        loki_start_ms, end_ms, step_s) if loki_start_ms < end_ms else None
    probe_task = loki_count_series(
        f"sum(count_over_time({LOKI_PROBE_SELECTOR} [{step_s}s]))",
        loki_start_ms, end_ms, step_s) if loki_start_ms < end_ms else None

    hp, probes, bans = await asyncio.gather(
        hp_task or asyncio.sleep(0, result={}),
        probe_task or asyncio.sleep(0, result={}),
        vm_count_series(start_ms, end_ms, step_s),
    )

    step_ms = step_s * 1000
    out = []
    t = (start_ms // step_ms) * step_ms
    while t <= end_ms:
        out.append({
            "t": t,
            "honeypot": _bucket_sum(hp, t, step_ms),
            "probes":   _bucket_sum(probes, t, step_ms),
            "bans":     _bucket_sum(bans, t, step_ms),
        })
        t += step_ms
    return {"buckets": out, "step_ms": step_ms,
            "start_ms": start_ms, "end_ms": end_ms}

def _bucket_sum(series: dict[int, int], t: int, step_ms: int) -> int:
    """Sum raw series points falling into [t, t+step_ms)."""
    return sum(v for ts, v in series.items() if t <= ts < t + step_ms)

# ---------------------------------------------------------------------------
# Grafana panel renders (proxied to grafana-reports; bearer stays server-side)
# ---------------------------------------------------------------------------
REPORT_PANELS = {  # allowlist — never proxy arbitrary uid/panel
    "map":       {"uid": "crowdsec-threats", "panel_id": 1, "label": "Cyberthreats Map",           "w": 1000, "h": 500},
    "countries": {"uid": "crowdsec-threats", "panel_id": 4, "label": "Top 10 Cyberthreat Countries", "w": 700,  "h": 500},
    "table":     {"uid": "crowdsec-threats", "panel_id": 3, "label": "Realtime Cyberthreats",       "w": 1000, "h": 500},
}
_report_cache: OrderedDict[tuple, dict] = OrderedDict()
_REPORT_CACHE_MAX = 8

@app.post("/api/report")
async def report(req: Request):
    if not REPORTS_TOKEN:
        raise HTTPException(status_code=503, detail="report rendering not configured")
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    panel_key = body.get("panel", "")
    panel = REPORT_PANELS.get(panel_key) if isinstance(panel_key, str) else None
    if not panel:
        raise HTTPException(status_code=400,
                            detail=f"panel must be one of {sorted(REPORT_PANELS)}")
    now_ms = _now_ms()
    try:
        from_ms, to_ms = clamp_range(body.get("from_ms"), body.get("to_ms"), now_ms)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cache_key = (body["panel"], from_ms // 60000, to_ms // 60000)
    if cache_key in _report_cache:
        _report_cache.move_to_end(cache_key)
        return dict(_report_cache[cache_key], cached=True)

    payload = {
        "dashboard_uid": panel["uid"],
        "panel_id":      panel["panel_id"],
        "from_time":     str(from_ms),
        "to_time":       str(to_ms),
        "width":         panel["w"],
        "height":        panel["h"],
    }
    try:
        # The VPS renderer is slow (~40s observed) — generous timeout.
        async with httpx.AsyncClient(timeout=100) as client:
            r = await client.post(
                f"{REPORTS_URL}/report", json=payload,
                headers={"Authorization": f"Bearer {REPORTS_TOKEN}"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="render timed out")
    except Exception:
        raise HTTPException(status_code=502, detail="render engine unreachable")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"render failed ({r.status_code})")

    data = r.json()
    result = {
        "panel":      body["panel"],
        "label":      panel["label"],
        "from_ms":    from_ms,
        "to_ms":      to_ms,
        "png_base64": data.get("png_base64", ""),
    }
    _report_cache[cache_key] = result
    while len(_report_cache) > _REPORT_CACHE_MAX:
        _report_cache.popitem(last=False)
    return dict(result, cached=False)

# ---------------------------------------------------------------------------
# Background poller → WebSocket broadcast
# ---------------------------------------------------------------------------
_cursors: dict[str, int] = {}
_MAX_CURSOR_LAG_NS = 300 * 1_000_000_000  # never replay more than 5 min

async def _poll_loki_source(name: str, query: str, event_name: str,
                            norm, cap: int):
    end = _now_ns()
    start = max(_cursors.get(name, _ns_ago(30)), end - _MAX_CURSOR_LAG_NS)
    raw = await loki_query_range(query, start, end, limit=cap)
    if raw is None:
        return  # Loki hiccup — keep cursor, retry next cycle
    for e in raw:
        n = norm(e)
        if n:
            await manager.broadcast({"event": event_name, "data": n})
        _cursors[name] = max(_cursors.get(name, 0), e["_ts_ns"] + 1)
    if not raw:
        _cursors[name] = end

async def _poll_crowdsec():
    """LAPI decision stream. startup=false is per-bouncer delta state, so the
    first pull after a restart naturally includes the missed backlog."""
    try:
        async with httpx.AsyncClient(timeout=5) as cs:
            r = await cs.get(
                f"{CROWDSEC_URL}/v1/decisions/stream",
                params={"startup": "false"},
                headers={"X-Api-Key": CROWDSEC_KEY},
            )
            if r.status_code != 200:
                return
            data = r.json() or {}
    except Exception:
        return
    now_ms = _now_ms()
    for dec in (data.get("new") or [])[:20]:
        geo = geoip_local(dec.get("value", ""))
        n = normalize_decision(dec, geo, now_ms)
        if n:
            await manager.broadcast({"event": "ban", "data": n})

async def poll_loop():
    _cursors["honeypot"] = _ns_ago(30)
    _cursors["probes"] = _ns_ago(30)
    while True:
        await asyncio.sleep(POLL_SECS)
        if not manager.active:
            continue
        await _poll_loki_source("honeypot", LOKI_HONEYPOT_QUERY, "attack",
                                normalize_honeypot, 20)
        await _poll_loki_source("probes", LOKI_PROBE_QUERY, "probe",
                                normalize_traefik, 30)
        if CROWDSEC_KEY:
            await _poll_crowdsec()

@app.on_event("startup")
async def startup():
    asyncio.create_task(poll_loop())

# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    origin = ws.headers.get("origin", "")
    if origin and origin not in WS_ORIGINS:
        await ws.close(code=4403)
        return
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
