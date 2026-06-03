from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from dataclasses import dataclass

from telegram_gateway.config import (
    CLAUDE_CLI_PATH, CODER_APPROVER_MCP_CONFIG, CODER_AUTO_ALLOW_TOOLS,
    CODER_HEARTBEAT_MINUTES, CODER_MODEL,
)
from telegram_gateway.formatter import format_tool_use, format_tool_result

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedItem:
    """One unit of the progress feed derived from a stream-json event."""
    kind: str          # "session" | "text" | "tool_use" | "tool_result" | "result"
    text: str
    detail: str = ""   # tool input summary, for tool_use


def _summarize_input(tool_input: dict) -> str:
    """Compact one-line-ish summary of a tool's input for the feed."""
    if not isinstance(tool_input, dict):
        result = str(tool_input)
    else:
        for key in ("command", "file_path", "path", "pattern", "query"):
            if key in tool_input:
                result = f"{key}: {tool_input[key]}"
                break
        else:
            result = ", ".join(f"{k}: {v}" for k, v in list(tool_input.items())[:3])
    if len(result) > 200:
        result = result[:200] + "…"
    return result


def parse_stream_event(event: dict) -> list[FeedItem]:
    """Map a single `--output-format stream-json` event to feed items.

    Returns [] for events that produce no user-visible output.
    """
    etype = event.get("type")

    if etype == "system" and event.get("subtype") == "init":
        sid = event.get("session_id")
        return [FeedItem(kind="session", text=sid)] if sid else []

    if etype == "assistant":
        items: list[FeedItem] = []
        for block in event.get("message", {}).get("content", []):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and block.get("text", "").strip():
                items.append(FeedItem(kind="text", text=block["text"].strip()))
            elif btype == "tool_use":
                items.append(FeedItem(
                    kind="tool_use",
                    text=block.get("name", "tool"),
                    detail=_summarize_input(block.get("input", {})),
                ))
        return items

    if etype == "user":
        items = []
        for block in event.get("message", {}).get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):  # content can be a block list
                    content = " ".join(
                        b.get("text", "") for b in content if isinstance(b, dict))
                items.append(FeedItem(kind="tool_result", text=str(content)))
        return items

    if etype == "result":
        return [FeedItem(kind="result", text=str(event.get("result") or ""))]

    return []


def build_permission_prompt(tool_name: str, tool_input: dict) -> str:
    """Human-readable approval text shown on the Telegram Approve/Deny card."""
    summary = _summarize_input(tool_input)
    return f"Run {tool_name}?\n{summary}" if summary else f"Run {tool_name}?"


def decide_from_status(status: str) -> dict:
    """Map a gateway.approvals status to the CLI permission-prompt contract."""
    if status == "approved":
        return {"behavior": "allow"}
    if status == "expired":
        return {"behavior": "deny", "message": "Approval request expired."}
    return {"behavior": "deny", "message": "Denied by operator."}


# --- Active-session registry (one global coder session at a time) ---
_active_chat_id: int | None = None
_active_procs: dict[int, asyncio.subprocess.Process] = {}


def active_coder_chat() -> int | None:
    """Chat ID of the currently running coder session, or None."""
    return _active_chat_id


def is_running(chat_id: int) -> bool:
    return chat_id in _active_procs


async def cancel_coder(chat_id: int) -> bool:
    """Terminate the running subprocess for a chat. Returns True if one existed."""
    proc = _active_procs.get(chat_id)
    if proc and proc.returncode is None:
        proc.terminate()
        # proc.wait()/reaping is handled by process_coder_command's finally
        return True
    return False


async def _render(chat_id: int, item: FeedItem) -> None:
    from telegram_gateway.bot import send_telegram_message
    if item.kind == "text":
        await send_telegram_message(chat_id, item.text)
    elif item.kind == "tool_use":
        await send_telegram_message(
            chat_id, format_tool_use(item.text, item.detail), parse_mode="HTML")
    elif item.kind == "tool_result":
        await send_telegram_message(
            chat_id, format_tool_result(item.text), parse_mode="HTML")
    elif item.kind == "result":
        await send_telegram_message(chat_id, item.text or "Done.")


async def _heartbeat(chat_id: int, started: float) -> None:
    from telegram_gateway.bot import send_telegram_message
    if CODER_HEARTBEAT_MINUTES <= 0:
        return
    while True:
        await asyncio.sleep(CODER_HEARTBEAT_MINUTES * 60)
        mins = int((asyncio.get_running_loop().time() - started) / 60)
        await send_telegram_message(chat_id, f"⏳ still working — {mins} min elapsed")


async def process_coder_command(command_id: int) -> None:
    """JobQueue handler: run one coder turn, streaming a progress feed."""
    from telegram_gateway import db
    from telegram_gateway.bot import send_telegram_message
    global _active_chat_id
    pool = await db.get_pool()
    cmd = await pool.fetchrow("SELECT * FROM gateway.commands WHERE id=$1", command_id)
    if not cmd:
        return
    chat_id = cmd["telegram_chat_id"]
    prompt = cmd["message"]

    session = await db.get_session(chat_id)
    session_id = session["session_id"] if session else None

    # Build CLI args. --resume must be its own flag pair (mirrors agent.py).
    if session_id:
        args = [CLAUDE_CLI_PATH, "--resume", session_id, "-p", prompt]
    else:
        args = [CLAUDE_CLI_PATH, "-p", prompt]
    args += ["--model", CODER_MODEL, "--output-format", "stream-json", "--verbose",
             "--mcp-config", CODER_APPROVER_MCP_CONFIG,
             "--permission-prompt-tool", "mcp__approver__permission_prompt",
             "--allowedTools", CODER_AUTO_ALLOW_TOOLS]

    logger.info("coder command %d started for chat %d", command_id, chat_id)
    started = asyncio.get_running_loop().time()
    hb = asyncio.create_task(_heartbeat(chat_id, started))
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd="/workspace", env={**os.environ})
        _active_procs[chat_id] = proc
        _active_chat_id = chat_id           # set AFTER registering proc for consistency

        stderr_chunks: list[bytes] = []

        async def _drain_stderr() -> None:
            assert proc.stderr is not None
            async for line in proc.stderr:
                stderr_chunks.append(line)

        drain_task = asyncio.create_task(_drain_stderr())

        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            for item in parse_stream_event(event):
                if item.kind == "session" and item.text:
                    # Persist session_id IMMEDIATELY so /cancel keeps resumability.
                    await db.upsert_session(chat_id, item.text, "coder")
                else:
                    await _render(chat_id, item)

        await drain_task
        await proc.wait()
        logger.info("coder command %d exit=%s", command_id, proc.returncode)
        if proc.returncode not in (0, None):
            err = b"".join(stderr_chunks).decode("utf-8", "replace")[-500:]
            await send_telegram_message(chat_id, f"⚠ coder exited {proc.returncode}\n{err}")
        await db.update_command_status(
            command_id, "completed",
            completed_at=datetime.now(timezone.utc),
        )
    finally:
        hb.cancel()
        _active_procs.pop(chat_id, None)
        _active_chat_id = None
