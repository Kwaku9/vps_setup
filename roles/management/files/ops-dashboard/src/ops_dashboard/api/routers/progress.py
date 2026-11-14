"""Student progress: what each student opened across the platform, for mentoring.

Admin role only. Reads the mentoring.* history written hourly by the VPS rollup
(roles/monitoring/templates/student-activity.py.j2): Grafana dashboards, decks
(with the furthest slide reached), timeline, threat map, charts, portal, the
Voices page, Access logins and refusals, and Open WebUI chat counts. Metadata
only: no chat text, no search terms. Limited to current members of the
students group, so the owner's own traffic and former students drop out.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..auth import require_role
from . import students as authentik

router = APIRouter(prefix="/api/students", tags=["students"])

RESOURCE_LABEL = {
    "grafana": "Grafana", "decks": "Decks", "timeline": "Timeline", "threat": "Threat map",
    "charts": "Charts", "portal": "Portal", "tts": "Voices", "openwebui": "Open WebUI", "login": "Sign-ins",
}


def _label(resource: str, item: str, titles: dict) -> str:
    kind, _, name = item.partition(":")
    if kind == "dashboard":
        return titles.get(name, name)
    if kind in ("deck", "page", "api", "model"):
        return "home page" if item == "page:home" else name
    if kind == "refused":
        return f"refused at {name}"
    return item.replace("_", " ")


@router.get("/progress")
async def progress(request: Request, days: int = Query(30, ge=1, le=365),
                   _: dict = Depends(require_role("admin"))):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "No database connection.")
    async with authentik._client() as c:
        people = [p for p in await authentik._all_people(c) if authentik.GROUP in p["groups"]]
    by_email = {p["email"].lower(): p for p in people if p.get("email")}
    emails = list(by_email)
    if not emails:
        return {"days": days, "students": []}

    async with pool.acquire() as conn:
        titles = {r["uid"]: r["title"] for r in await conn.fetch("SELECT uid, title FROM mentoring.dashboards")}
        rows = await conn.fetch(
            "SELECT email, day, resource, item, hits, last_seen FROM mentoring.activity "
            "WHERE email = ANY($1::text[]) AND day > current_date - $2::int", emails, days)
        decks = await conn.fetch(
            "SELECT email, deck, slides_total, max_slide, cardinality(slides_seen) AS seen, first_seen, last_seen "
            "FROM mentoring.deck_progress WHERE email = ANY($1::text[]) ORDER BY last_seen DESC", emails)
        ever = await conn.fetch(
            "SELECT email, max(last_seen) AS last_seen FROM mentoring.activity "
            "WHERE email = ANY($1::text[]) AND resource <> 'openwebui' GROUP BY email", emails)

    out = {}
    for e, p in by_email.items():
        out[e] = {"email": e, "name": p.get("name") or p.get("username"), "username": p.get("username"),
                  "last_login": p.get("last_login"), "last_seen": None, "days_active": 0,
                  "by_resource": {}, "items": {}, "decks": [], "openwebui": {"chats_active": 0, "chats_started": 0, "models": {}},
                  "refused": {}, "daily": {}}
    for r in ever:
        out[r["email"]]["last_seen"] = r["last_seen"].isoformat()
    active_days: dict[str, set] = {e: set() for e in out}
    for r in rows:
        s = out[r["email"]]
        res, item, hits = r["resource"], r["item"], r["hits"]
        day = r["day"].isoformat()
        if res == "openwebui":
            if item in ("chats_active", "chats_started"):
                s["openwebui"][item] += hits
            elif item.startswith("model:"):
                m = item[6:]
                s["openwebui"]["models"][m] = s["openwebui"]["models"].get(m, 0) + hits
            if item == "chats_active":
                active_days[r["email"]].add(day)
                s["daily"][day] = s["daily"].get(day, 0) + hits
            continue
        if res == "login":
            if item.startswith("refused:"):
                d = item[8:]
                s["refused"][d] = s["refused"].get(d, 0) + hits
            continue
        active_days[r["email"]].add(day)
        s["daily"][day] = s["daily"].get(day, 0) + hits
        s["by_resource"][res] = s["by_resource"].get(res, 0) + hits
        key = (res, item)
        it = s["items"].setdefault(key, {"resource": res, "resource_label": RESOURCE_LABEL.get(res, res),
                                         "label": _label(res, item, titles), "hits": 0, "last_seen": None})
        it["hits"] += hits
        ls = r["last_seen"].isoformat()
        it["last_seen"] = max(it["last_seen"] or ls, ls)
    for d in decks:
        total = max(d["slides_total"], 1)
        done = d["max_slide"] >= total - 1
        out[d["email"]]["decks"].append({
            "deck": d["deck"], "slides_total": d["slides_total"], "furthest": d["max_slide"] + 1,
            "seen": d["seen"], "percent": round(100 * (d["max_slide"] + 1) / total),
            "status": "finished" if done else "started", "first_seen": d["first_seen"].isoformat(),
            "last_seen": d["last_seen"].isoformat()})

    students = []
    for e, s in out.items():
        s["days_active"] = len(active_days[e])
        s["items"] = sorted(s["items"].values(), key=lambda i: (-i["hits"], i["label"]))[:25]
        s["by_resource"] = [{"resource": k, "label": RESOURCE_LABEL.get(k, k), "hits": v}
                            for k, v in sorted(s["by_resource"].items(), key=lambda kv: -kv[1])]
        s["daily"] = [{"day": k, "hits": v} for k, v in sorted(s["daily"].items())]
        s["openwebui"]["models"] = sorted(({"model": k, "chats": v} for k, v in s["openwebui"]["models"].items()),
                                          key=lambda m: -m["chats"])
        s["refused"] = [{"domain": k, "count": v} for k, v in s["refused"].items()]
        s["needs_attention"] = [d["deck"] for d in s["decks"] if d["status"] == "started"]
        students.append(s)
    students.sort(key=lambda s: s["last_seen"] or "", reverse=True)
    return {"days": days, "students": students}
