"""Approval rows must always reach a terminal status.

Two independent mechanisms guarantee that, and both are covered here:

  * the requester closing its own row when it stops polling (abandon_approval),
  * the background sweep catching everything else once the TTL lapses
    (expire_stale_approvals, driven by main._expire_approvals).

Before these existed, a PreToolUse hook that timed out and fell back to the
local CLI prompt left its row 'pending' forever — 1,110 of them accumulated.
"""
import asyncio

import pytest

from telegram_gateway import db
from telegram_gateway.models import ApprovalStatus


class FakePool:
    """Records SQL and replays a canned asyncpg-style command tag."""

    def __init__(self, execute_result="UPDATE 1"):
        self.calls = []
        self.execute_result = execute_result
        self.row = None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return self.execute_result

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


# --- abandon_approval -------------------------------------------------------

def test_abandoned_is_a_distinct_terminal_status():
    # 'expired' means the TTL lapsed; 'abandoned' means the requester left
    # early. Collapsing them would hide which mechanism closed the row.
    assert ApprovalStatus.ABANDONED.value == "abandoned"
    assert ApprovalStatus.ABANDONED != ApprovalStatus.EXPIRED


async def test_abandon_only_touches_pending_rows(fake_pool):
    await db.abandon_approval(42, "poll timeout")
    kind, sql, args = fake_pool.calls[-1]
    assert kind == "execute"
    # The guard is the whole safety story: without it a decision landing in the
    # race window between the hook's timeout and this call gets clobbered.
    assert "status = 'pending'" in sql
    assert "SET status = 'abandoned'" in sql
    assert args == (42, "poll timeout")


async def test_abandon_reports_winning_the_race(fake_pool):
    fake_pool.execute_result = "UPDATE 1"
    assert await db.abandon_approval(1) is True


async def test_abandon_reports_losing_the_race(fake_pool):
    # "UPDATE 0" => the row was already approved/denied. The caller must be able
    # to tell, so it can report the real decision instead of claiming a close.
    fake_pool.execute_result = "UPDATE 0"
    assert await db.abandon_approval(1) is False


async def test_abandon_survives_an_unparseable_command_tag(fake_pool):
    fake_pool.execute_result = ""
    assert await db.abandon_approval(1) is False


async def test_abandon_records_a_default_reason(fake_pool):
    await db.abandon_approval(7)
    _, _, args = fake_pool.calls[-1]
    assert args[1], "a reason is always persisted for later forensics"


# --- expire_stale_approvals -------------------------------------------------

async def test_expire_sweep_targets_only_lapsed_pending_rows(fake_pool):
    fake_pool.execute_result = "UPDATE 3"
    assert await db.expire_stale_approvals() == 3
    _, sql, _ = fake_pool.calls[-1]
    assert "status = 'pending'" in sql
    assert "expires_at <= now()" in sql


# --- the background sweep task ---------------------------------------------

async def test_reaper_task_actually_runs_the_sweep(monkeypatch):
    """The regression that produced the backlog: expire_stale_approvals()
    existed and was correct, but nothing ever called it."""
    from telegram_gateway import main

    calls = []

    async def _sweep():
        calls.append(1)
        return 1

    monkeypatch.setattr(main.db, "expire_stale_approvals", _sweep)
    monkeypatch.setattr(main, "APPROVAL_REAPER_INTERVAL_SECONDS", 0)

    task = asyncio.create_task(main._expire_approvals())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls, "the reaper loop never invoked the sweep"


async def test_reaper_keeps_going_after_a_failed_pass(monkeypatch):
    """A transient DB blip must not silently kill the loop for the process's
    remaining lifetime — that would recreate the backlog."""
    from telegram_gateway import main

    calls = []

    async def _sweep():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("connection reset")
        return 0

    monkeypatch.setattr(main.db, "expire_stale_approvals", _sweep)
    monkeypatch.setattr(main, "APPROVAL_REAPER_INTERVAL_SECONDS", 0)

    task = asyncio.create_task(main._expire_approvals())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(calls) > 1, "loop stopped after the first exception"


# --- POST /abandon_approval -------------------------------------------------


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from telegram_gateway.tools.commands import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _stub_approval(monkeypatch, row, abandoned=True):
    async def _get(approval_id):
        return row

    async def _abandon(approval_id, reason=None):
        return abandoned

    monkeypatch.setattr(db, "get_approval", _get)
    monkeypatch.setattr(db, "abandon_approval", _abandon)


def test_abandon_endpoint_404s_on_unknown_id(client, monkeypatch):
    _stub_approval(monkeypatch, None)
    body = client.post("/abandon_approval", json={"approval_id": 999}).json()
    assert body == {"ok": False, "error": "Approval not found"}


def test_abandon_endpoint_closes_a_pending_row(client, monkeypatch):
    # telegram_message_id None => no card to edit, so no Telegram call is made.
    _stub_approval(monkeypatch, {
        "id": 1, "status": "pending", "telegram_message_id": None,
        "telegram_chat_id": 5, "prompt_text": "Tool: Bash",
    })
    body = client.post(
        "/abandon_approval", json={"approval_id": 1, "reason": "poll timeout"}
    ).json()
    assert body == {"ok": True, "abandoned": True, "status": "abandoned"}


def test_abandon_endpoint_reports_a_decision_that_beat_it(client, monkeypatch):
    # The operator tapped Approve in the window between the hook giving up and
    # this request landing. Report what stuck; never claim we closed the row.
    _stub_approval(monkeypatch, {
        "id": 1, "status": "pending", "telegram_message_id": None,
        "telegram_chat_id": 5, "prompt_text": "Tool: Bash",
    }, abandoned=False)

    async def _get_decided(approval_id):
        return {"id": 1, "status": "approved"}

    monkeypatch.setattr(db, "get_approval", _get_decided)
    body = client.post("/abandon_approval", json={"approval_id": 1}).json()
    assert body == {"ok": True, "abandoned": False, "status": "approved"}


def test_abandon_endpoint_survives_a_telegram_failure(client, monkeypatch):
    """The row is already closed by the time we touch Telegram — a failed card
    edit is cosmetic and must not turn into a 500 the hook has to handle."""
    _stub_approval(monkeypatch, {
        "id": 1, "status": "pending", "telegram_message_id": 77,
        "telegram_chat_id": 5, "prompt_text": "Tool: Bash",
    })

    from telegram_gateway import bot

    async def _boom(*a, **kw):
        raise RuntimeError("telegram 429")

    monkeypatch.setattr(bot, "edit_message_text", _boom)
    body = client.post("/abandon_approval", json={"approval_id": 1}).json()
    assert body == {"ok": True, "abandoned": True, "status": "abandoned"}
