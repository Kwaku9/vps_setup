from __future__ import annotations
import json, logging
import httpx
from rapidfuzz import fuzz
from grafana_reports.models import Category, Candidate
from grafana_reports.config import Settings
from grafana_reports.timeparse import parse_time_phrase

log = logging.getLogger("grafana_reports.resolver")

def _index(categories: list[Category]):
    for cat in categories:
        for dash in cat.dashboards:
            for panel in dash.panels:
                terms = [panel.label, panel.title, *panel.synonyms]
                yield cat, dash, panel, terms

def _exists(categories, uid, pid) -> bool:
    return any(d.uid == uid and any(p.panel_id == pid for p in d.panels)
               for c in categories for d in c.dashboards)

async def resolve(query: str, categories: list[Category], settings: Settings, llm=None) -> list[Candidate]:
    frm, to, leftover = parse_time_phrase(query)
    scored: list[Candidate] = []
    for cat, dash, panel, terms in _index(categories):
        score = max((fuzz.WRatio(leftover, t) for t in terms), default=0.0)
        scored.append(Candidate(cat.name, dash.uid, panel.panel_id, panel.label,
                                frm, to, round(score, 1), "fuzzy"))
    scored.sort(key=lambda c: c.confidence, reverse=True)
    top = scored[0].confidence if scored else 0.0
    if top < settings.fuzzy_threshold and llm is not None:
        cand = await llm(query, categories, settings)
        if cand is not None and _exists(categories, cand.dashboard_uid, cand.panel_id):
            return [cand]
        log.info("llm fallback rejected (no candidate or not in catalog)")
    return scored

async def llm_resolve(query: str, categories: list[Category], settings: Settings) -> Candidate | None:
    if not settings.litellm_url:
        return None
    options = [{"category": c.name, "dashboard_uid": d.uid, "panel_id": p.panel_id, "label": p.label}
               for c in categories for d in c.dashboards for p in d.panels]
    frm, to, _ = parse_time_phrase(query)
    prompt = (
        "You map a user request to ONE panel from the allowed list. "
        "Respond ONLY with JSON {\"dashboard_uid\":..,\"panel_id\":..}. "
        "panel_id MUST be one from the list.\n"
        f"Allowed: {json.dumps(options)}\nRequest: {query}"
    )
    headers = {"Content-Type": "application/json"}
    if settings.litellm_key:
        headers["Authorization"] = f"Bearer {settings.litellm_key}"
    body = {"model": settings.litellm_model, "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "response_format": {"type": "json_object"}}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{settings.litellm_url}/chat/completions", json=body, headers=headers)
    r.raise_for_status()
    data = json.loads(r.json()["choices"][0]["message"]["content"])
    for cat in categories:
        for d in cat.dashboards:
            for p in d.panels:
                if d.uid == data.get("dashboard_uid") and p.panel_id == data.get("panel_id"):
                    return Candidate(cat.name, d.uid, p.panel_id, p.label, frm, to, 0.85, "llm")
    return None
