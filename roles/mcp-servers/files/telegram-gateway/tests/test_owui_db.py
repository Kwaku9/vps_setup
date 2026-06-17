import pytest

from telegram_gateway import db


class FakePool:
    def __init__(self):
        self.calls = []
        self.row = None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self.row


@pytest.fixture
def fake_pool(monkeypatch):
    fp = FakePool()

    async def _get_pool():
        return fp

    monkeypatch.setattr(db, "get_pool", _get_pool)
    return fp


def test_schema_defines_owui_sessions():
    assert "gateway.owui_sessions" in db.SCHEMA_SQL
    assert "owui_chat_id" in db.SCHEMA_SQL


async def test_upsert_owui_binding(fake_pool):
    await db.upsert_owui_binding("c1", "/w", "s1")
    kind, sql, args = fake_pool.calls[-1]
    assert kind == "execute"
    assert "gateway.owui_sessions" in sql
    assert args == ("c1", "/w", "s1")


async def test_upsert_owui_binding_null_session(fake_pool):
    await db.upsert_owui_binding("c1", "/w", None)
    assert fake_pool.calls[-1][2] == ("c1", "/w", None)


async def test_get_owui_binding(fake_pool):
    fake_pool.row = {"owui_chat_id": "c1", "session_id": "s1"}
    row = await db.get_owui_binding("c1")
    kind, sql, args = fake_pool.calls[-1]
    assert kind == "fetchrow"
    assert "gateway.owui_sessions" in sql
    assert args == ("c1",)
    assert row["session_id"] == "s1"


async def test_clear_owui_binding(fake_pool):
    await db.clear_owui_binding("c1")
    kind, sql, args = fake_pool.calls[-1]
    assert kind == "execute"
    assert "DELETE" in sql.upper()
    assert args == ("c1",)
