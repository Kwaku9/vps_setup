"""Nightly backup outages must not produce tracebacks / log floods.

The 06:00 vps-backup stops shared-db-pod and logs-pod for ~15 min. Before this,
every approval sweep in that window logged a full asyncpg TimeoutError
traceback, and the OTLP exporter logged ~230 resolve/export failures.
"""
import asyncio
import logging

import asyncpg
import pytest


async def _run_sweeps(monkeypatch, outcomes, caplog):
    from telegram_gateway import main

    seq = list(outcomes)

    async def _sweep():
        if not seq:
            await asyncio.sleep(3600)
        o = seq.pop(0)
        if isinstance(o, BaseException):
            raise o
        return o

    monkeypatch.setattr(main.db, "expire_stale_approvals", _sweep)
    monkeypatch.setattr(main, "APPROVAL_REAPER_INTERVAL_SECONDS", 0)
    caplog.set_level(logging.INFO, logger=main.logger.name)
    task = asyncio.create_task(main._expire_approvals())
    for _ in range(200):
        await asyncio.sleep(0)
        if not seq:
            break
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return [r for r in caplog.records if r.name == main.logger.name]


async def test_db_outage_logs_one_warning_no_traceback(monkeypatch, caplog):
    recs = await _run_sweeps(
        monkeypatch,
        [TimeoutError(), TimeoutError(), OSError("refused"),
         asyncpg.CannotConnectNowError("starting up"), 2],
        caplog,
    )
    warnings = [r for r in recs if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "database unreachable" in warnings[0].getMessage()
    assert not [r for r in recs if r.levelno >= logging.ERROR]
    assert not [r for r in recs if r.exc_info]
    msgs = [r.getMessage() for r in recs]
    assert any("reachable again after 4" in m for m in msgs)
    assert any("Expired 2 stale approval(s)" in m for m in msgs)


async def test_long_db_outage_escalates_to_error_once(monkeypatch, caplog):
    from telegram_gateway import main

    monkeypatch.setattr(main, "SWEEP_OUTAGE_ESCALATE_AFTER", 3)
    recs = await _run_sweeps(monkeypatch, [TimeoutError()] * 6, caplog)
    errors = [r for r in recs if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "3 consecutive" in errors[0].getMessage()


async def test_unexpected_error_still_logs_traceback(monkeypatch, caplog):
    recs = await _run_sweeps(monkeypatch, [RuntimeError("bug")], caplog)
    assert any(r.exc_info and r.levelno == logging.ERROR for r in recs)


def _rec(level, msg, *args):
    return logging.LogRecord("x", level, __file__, 1, msg, args, None)


def test_otlp_failure_spam_throttled():
    from telegram_gateway.tracing import ThrottleExportFailures

    now = [0.0]
    f = ThrottleExportFailures(interval_seconds=600, clock=lambda: now[0])

    first = _rec(logging.WARNING, "Transient error %s", "Failed to resolve 'logs-pod'")
    assert f.filter(first)
    for _ in range(20):
        now[0] += 10
        assert not f.filter(_rec(logging.WARNING, "Transient error %s", "x"))
    assert not f.filter(_rec(logging.ERROR, "Failed to export span batch"))

    now[0] += 600
    later = _rec(logging.ERROR, "Failed to export span batch")
    assert f.filter(later)
    assert later.levelno == logging.WARNING and later.levelname == "WARNING"
    assert "21 similar" in later.getMessage()

    # INFO/DEBUG are never throttled
    assert f.filter(_rec(logging.INFO, "ok"))
