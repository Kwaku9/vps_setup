"""Host rehearsal: how the workshop host is practising in the buildfol.io Command Center.

Admin role only. Reads the host_* events that buildfol.io/command-center?mode=host sends
to PostHog (portfolio_site_repo src/analytics, EV.HOST_*): visits, a heartbeat for every
visible minute tagged with where she was, practice panels opened and closed, takes
recorded (with a per-section take number, so re-records = takes - 1), plays of her own
takes, the coaching note and the example wording, briefing slides and completion, and
clicks on "Edit the script". Activity only: the recordings never leave her device.

Only tracking_version >= TRACKING_FROM counts. Version 3 began 2026-11-14 11:54 UTC, after
the end-to-end test, so earlier test traffic stays out.
"""
from __future__ import annotations

import os
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_role

router = APIRouter(prefix="/api/students", tags=["students"])

POSTHOG_HOST = os.environ.get("BUILDFOLIO_POSTHOG_API_HOST", "https://us.posthog.com").rstrip("/")
# "@current" = the project the key's owner has selected; the key is limited to the Buildfolio org.
POSTHOG_PROJECT = os.environ.get("BUILDFOLIO_POSTHOG_PROJECT", "@current")
TRACKING_FROM = 3
BRIEFING_SLIDES = 15
CACHE_SECONDS = 60

# Section ids from the host deck (07-host-deck/build_host_deck.py CC_SECTIONS), in script order.
SECTIONS = [
    ("role", "Your role in four moments", False, None),
    ("welcome", "Welcome", True, 180),
    ("company", "Introducing the company", True, 30),
    ("presenter", "Introducing the presenter", True, 60),
    ("facts", "Your words. These facts exactly.", False, None),
    ("chat", "Chat monitor", False, None),
    ("closing", "Closing", False, 300),
    ("zoom", "Zoom back out", True, 30),
    ("next", "The invitation and the thank-you", True, None),
    ("dodont", "Do and don't", False, None),
]
PLACES = [("briefing", "Watching the briefing"), ("room", "In the room")]

_cache: dict[int, tuple[float, dict]] = {}


def _key() -> str:
    return os.environ.get("BUILDFOLIO_POSTHOG_PERSONAL_API_KEY", "")


async def _hogql(client: httpx.AsyncClient, sql: str) -> list[list]:
    r = await client.post(f"{POSTHOG_HOST}/api/projects/{POSTHOG_PROJECT}/query/",
                          json={"query": {"kind": "HogQLQuery", "query": sql}},
                          headers={"Authorization": f"Bearer {_key()}"})
    if r.status_code != 200:
        raise HTTPException(502, f"PostHog query failed ({r.status_code}).")
    return r.json().get("results") or []


def _queries(days: int) -> dict[str, str]:
    base = (f"event LIKE 'host_%' AND toFloat(properties.tracking_version) >= {TRACKING_FROM} "
            f"AND timestamp > now() - INTERVAL {int(days)} DAY")
    host = "properties.rehearsal_host"
    return {
        "totals": f"""
            SELECT {host}, countIf(event = 'host_room_opened'), uniq(toDate(timestamp)),
                   countIf(event = 'host_practice_minute'), countIf(event = 'host_take_recorded'),
                   countIf(event = 'host_take_played'), countIf(event = 'host_audio_played'),
                   countIf(event = 'host_briefing_completed'),
                   uniqIf(properties.slide, event = 'host_briefing_slide'),
                   countIf(event = 'host_script_edit_opened'), min(timestamp), max(timestamp)
            FROM events WHERE {base} AND {host} IS NOT NULL GROUP BY 1""",
        "sections": f"""
            SELECT {host}, coalesce(properties.section, properties.where),
                   countIf(event = 'host_practice_minute'), countIf(event = 'host_section_opened'),
                   sumIf(toFloat(properties.seconds), event = 'host_section_closed'),
                   countIf(event = 'host_take_recorded'),
                   avgIf(toFloat(properties.seconds), event = 'host_take_recorded'),
                   countIf(event = 'host_take_played'), countIf(event = 'host_audio_played'), max(timestamp)
            FROM events WHERE {base} AND {host} IS NOT NULL GROUP BY 1, 2""",
        "daily": f"""
            SELECT {host}, toString(toDate(timestamp)), countIf(event = 'host_practice_minute'),
                   countIf(event = 'host_take_recorded')
            FROM events WHERE {base} AND {host} IS NOT NULL GROUP BY 1, 2 ORDER BY 2""",
        "visits": f"""
            SELECT {host}, timestamp, properties.$device_type, properties.$os, properties.$browser,
                   properties.$geoip_city_name
            FROM events WHERE {base} AND event = 'host_room_opened' AND {host} IS NOT NULL
            ORDER BY timestamp DESC LIMIT 60""",
        "denied": f"SELECT count() FROM events WHERE event = 'host_gate_denied' "
                  f"AND toFloat(properties.tracking_version) >= {TRACKING_FROM} "
                  f"AND timestamp > now() - INTERVAL {int(days)} DAY",
    }


def _num(v, cast=int):
    try:
        return cast(v) if v is not None else cast(0)
    except (TypeError, ValueError):
        return cast(0)


def assemble(days: int, rows: dict[str, list[list]]) -> dict:
    """Turn the five query results into one card per person. Pure, so it is tested directly."""
    people: dict[str, dict] = {}
    for r in rows["totals"]:
        name = r[0]
        people[name] = {
            "name": name, "visits": _num(r[1]), "active_days": _num(r[2]), "minutes": _num(r[3]),
            "takes": _num(r[4]), "playbacks": _num(r[5]), "listens": _num(r[6]),
            "briefings_completed": _num(r[7]), "slides_reached": _num(r[8]), "slides_total": BRIEFING_SLIDES,
            "script_edits": _num(r[9]), "first_seen": r[10], "last_seen": r[11],
            "rerecords": 0, "sections": [], "places": [], "daily": [], "visits_recent": [],
        }

    found: dict[tuple[str, str], list] = {(r[0], r[1]): r for r in rows["sections"] if r[1]}
    for name, p in people.items():
        for sid, title, practice, target in SECTIONS:
            r = found.get((name, sid))
            takes = _num(r[5]) if r else 0
            p["sections"].append({
                "id": sid, "title": title, "practice": practice, "target_seconds": target,
                "minutes": _num(r[2]) if r else 0, "opens": _num(r[3]) if r else 0,
                "seconds_open": round(_num(r[4], float)) if r else 0, "takes": takes,
                "rerecords": max(takes - 1, 0), "avg_take_seconds": round(_num(r[6], float), 1) if r and takes else None,
                "playbacks": _num(r[7]) if r else 0, "listens": _num(r[8]) if r else 0,
                "last": r[9] if r else None,
            })
        p["rerecords"] = sum(s["rerecords"] for s in p["sections"])
        for pid, title in PLACES:
            r = found.get((name, pid))
            p["places"].append({"id": pid, "title": title, "minutes": _num(r[2]) if r else 0})

    for r in rows["daily"]:
        if r[0] in people:
            people[r[0]]["daily"].append({"day": r[1], "minutes": _num(r[2]), "takes": _num(r[3])})
    for r in rows["visits"]:
        if r[0] in people and len(people[r[0]]["visits_recent"]) < 12:
            people[r[0]]["visits_recent"].append({"at": r[1], "device": r[2], "os": r[3], "browser": r[4], "city": r[5]})

    order = {"Nalah": 0}  # the host first, test logins after
    hosts = sorted(people.values(), key=lambda p: (order.get(p["name"], 1), p["name"]))
    denied = _num(rows["denied"][0][0]) if rows.get("denied") else 0
    return {"days": days, "configured": True, "tracking_from": TRACKING_FROM, "hosts": hosts, "gate_denied": denied}


@router.get("/host-rehearsal")
async def host_rehearsal(days: int = Query(30, ge=1, le=365), _: dict = Depends(require_role("admin"))):
    if not _key():
        return {"days": days, "configured": False, "tracking_from": TRACKING_FROM, "hosts": [], "gate_denied": 0}
    hit = _cache.get(days)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    async with httpx.AsyncClient(timeout=30) as c:
        rows = {name: await _hogql(c, sql) for name, sql in _queries(days).items()}
    out = assemble(days, rows)
    _cache[days] = (time.monotonic(), out)
    return out
