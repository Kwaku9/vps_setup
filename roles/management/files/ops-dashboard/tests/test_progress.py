"""Student progress view: only current students, decks summarised, labels readable."""
import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace

from ops_dashboard.api.routers import progress, students

T = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 11, 10)


class FakeConn:
    def __init__(self, tables):
        self.tables = tables

    async def fetch(self, sql, *args):
        if "mentoring.dashboards" in sql:
            return self.tables["dashboards"]
        emails = set(args[0])
        if "deck_progress" in sql:
            return [r for r in self.tables["decks"] if r["email"] in emails]
        if "max(last_seen)" in sql:
            seen = {}
            for r in self.tables["activity"]:
                if r["email"] in emails and r["resource"] != "openwebui":
                    seen[r["email"]] = max(seen.get(r["email"], r["last_seen"]), r["last_seen"])
            return [{"email": e, "last_seen": t} for e, t in seen.items()]
        return [r for r in self.tables["activity"] if r["email"] in emails]


class FakePool:
    def __init__(self, tables):
        self.conn = FakeConn(tables)

    def acquire(self):
        pool = self

        class Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *a):
                return False
        return Ctx()


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def row(email, resource, item, hits=1):
    return {"email": email, "day": TODAY, "resource": resource, "item": item, "hits": hits, "last_seen": T}


def run(monkeypatch, tables):
    people = [
        {"pk": 1, "username": "stu", "name": "Stu Dent", "email": "stu@x.io", "groups": ["students"], "last_login": None},
        {"pk": 2, "username": "old", "name": "Former", "email": "old@x.io", "groups": ["free_users"], "last_login": None},
        {"pk": 3, "username": "owner", "name": "Owner", "email": "owner@x.io", "groups": ["admins"], "last_login": None},
    ]
    monkeypatch.setattr(students, "_client", lambda: FakeClient())

    async def all_people(c):
        return people
    monkeypatch.setattr(students, "_all_people", all_people)
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=FakePool(tables))))
    return asyncio.run(progress.progress(req, days=30, _={}))


def test_only_current_students_and_readable(monkeypatch):
    tables = {
        "dashboards": [{"uid": "abc", "title": "Container Status"}],
        "activity": [
            row("stu@x.io", "grafana", "dashboard:abc", 4),
            row("stu@x.io", "timeline", "api:search", 2),
            row("stu@x.io", "login", "refused:ops.aicortex.cloud"),
            row("stu@x.io", "openwebui", "chats_active", 3),
            row("stu@x.io", "openwebui", "model:free-chat", 3),
            row("old@x.io", "grafana", "dashboard:abc", 9),     # no longer a student
            row("owner@x.io", "grafana", "dashboard:abc", 50),  # admin
        ],
        "decks": [
            {"email": "stu@x.io", "deck": "graph-etl-deck", "slides_total": 14, "max_slide": 4, "seen": 3, "first_seen": T, "last_seen": T},
            {"email": "stu@x.io", "deck": "bruce-deck", "slides_total": 10, "max_slide": 9, "seen": 10, "first_seen": T, "last_seen": T},
        ],
    }
    out = run(monkeypatch, tables)
    assert [s["email"] for s in out["students"]] == ["stu@x.io"]
    s = out["students"][0]
    labels = {i["label"] for i in s["items"]}
    assert "Container Status" in labels and "search" in labels
    assert s["by_resource"][0] == {"resource": "grafana", "label": "Grafana", "hits": 4}
    assert s["openwebui"]["chats_active"] == 3 and s["openwebui"]["models"] == [{"model": "free-chat", "chats": 3}]
    assert s["refused"] == [{"domain": "ops.aicortex.cloud", "count": 1}]
    decks = {d["deck"]: d for d in s["decks"]}
    assert decks["graph-etl-deck"]["status"] == "started" and decks["graph-etl-deck"]["furthest"] == 5
    assert decks["bruce-deck"]["status"] == "finished" and decks["bruce-deck"]["percent"] == 100
    assert s["needs_attention"] == ["graph-etl-deck"]
    assert s["days_active"] == 1


def test_no_students_returns_empty(monkeypatch):
    monkeypatch.setattr(students, "_client", lambda: FakeClient())

    async def nobody(c):
        return [{"pk": 3, "username": "owner", "name": "Owner", "email": "owner@x.io", "groups": ["admins"], "last_login": None}]
    monkeypatch.setattr(students, "_all_people", nobody)
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=FakePool({"dashboards": [], "activity": [], "decks": []}))))
    assert asyncio.run(progress.progress(req, days=7, _={}))["students"] == []
