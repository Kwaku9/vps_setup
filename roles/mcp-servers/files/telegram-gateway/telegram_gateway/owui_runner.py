"""Frontend-agnostic Claude Code CLI turn runner.

Extracted from ``coder.py`` so both the Telegram coder and the OpenWebUI
session-resume service share one implementation of "spawn ``claude``, parse the
stream-json feed, yield items". The caller decides what to do with each item
(render to Telegram, stream as SSE, persist the session id, ...).

Also holds two pieces of cross-request state the OWUI service needs:
- ``workspace_lock`` — serialize turns that share a workspace (concurrent
  ``claude`` runs in one tree would race on files/git).
- the in-process approval registry — lets the Telegram-free ``/request_approval``
  hook intake hand a pending approval to the running ``/coder/stream`` so it can
  surface it as a native OpenWebUI confirmation.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable

from telegram_gateway.coder import FeedItem, parse_stream_event
from telegram_gateway.config import (
    CLAUDE_CLI_PATH, CODER_APPROVER_MCP_CONFIG, CODER_MODEL, OWUI_AUTO_ALLOW_TOOLS,
)

# --- per-workspace concurrency ---
_ws_locks: dict[str, asyncio.Lock] = {}


def workspace_lock(workspace: str) -> asyncio.Lock:
    return _ws_locks.setdefault(workspace, asyncio.Lock())


# --- in-process approval registry (run_id -> queue of approval dicts) ---
PENDING: dict[int, asyncio.Queue] = {}


def register_run(run_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    PENDING[run_id] = q
    return q


def push_approval(run_id: int, approval: dict) -> bool:
    """Hand a pending approval to a running stream. False if no such run."""
    q = PENDING.get(run_id)
    if q is None:
        return False
    q.put_nowait(approval)
    return True


def unregister_run(run_id: int) -> None:
    PENDING.pop(run_id, None)


async def run_coder_turn(
    prompt: str,
    cwd: str,
    session_id: str | None = None,
    env_overrides: dict | None = None,
    allowed_tools: str = OWUI_AUTO_ALLOW_TOOLS,
    on_proc: Callable[[asyncio.subprocess.Process], None] | None = None,
) -> AsyncIterator[tuple[FeedItem, int | None]]:
    """Run one ``claude`` turn in ``cwd``, yielding ``(FeedItem, code)``.

    ``code`` is None for every item except the terminal ``_exit`` sentinel,
    whose ``text`` is the trailing stderr and whose ``code`` is the exit status.
    ``on_proc`` (if given) is called with the live process once spawned — used by
    the Telegram path to register the process for ``/cancel``.
    """
    args = [CLAUDE_CLI_PATH]
    if session_id:
        args += ["--resume", session_id]
    args += ["-p", prompt, "--model", CODER_MODEL,
             "--output-format", "stream-json", "--verbose",
             "--mcp-config", CODER_APPROVER_MCP_CONFIG, "--strict-mcp-config",
             "--allowedTools", allowed_tools]
    env = {**os.environ, **(env_overrides or {})}
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=cwd, env=env)
    if on_proc:
        on_proc(proc)

    stderr_chunks: list[bytes] = []

    async def _drain_stderr() -> None:
        assert proc.stderr is not None
        async for ln in proc.stderr:
            stderr_chunks.append(ln)

    drain = asyncio.create_task(_drain_stderr())
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for item in parse_stream_event(event):
            yield item, None
    await drain
    await proc.wait()
    tail = b"".join(stderr_chunks).decode("utf-8", "replace")[-500:]
    yield FeedItem(kind="_exit", text=tail), proc.returncode
