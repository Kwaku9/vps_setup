"""Enumerate the real Claude Code sessions that live on the VPS.

Claude Code stores one JSONL transcript per session under
``~/.claude/projects/<path-encoded-workspace>/<session_id>.jsonl``. Each line
carries a ``cwd`` field (the workspace the session ran in) and, often, a
``{"type": "summary", "summary": ...}`` line. We decode the workspace by reading
``cwd`` from the transcript rather than un-mangling the directory name, which is
ambiguous (real path segments can contain dashes).

This module is intentionally pure (stdlib only) so it is trivially unit-testable
and carries no runtime dependencies.
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

PROJECTS_ROOT = os.environ.get("CC_PROJECTS_ROOT", "/root/.claude/projects")


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    workspace: str
    summary: str
    mtime_iso: str


def _first_text(content) -> str:
    """Best-effort short summary from a user message's content.

    Claude Code user content is usually a list of blocks, sometimes a plain
    string. Return the first text we find, truncated.
    """
    if isinstance(content, str):
        return content.strip()[:120]
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text", "")).strip()
                if text:
                    return text[:120]
    return ""


# Opening user turns that are NOT meaningful titles: injected agent context,
# OpenWebUI auto-tasks, harness reminders, slash-command/caveat wrappers.
_SKIP_TITLE_PREFIXES = (
    "[Context:", "### Task:", "<system-reminder", "<command-", "Caveat:")


def _clean_user_title(content) -> str:
    """First real user text usable as a title; '' for empty/injected blobs."""
    text = _first_text(content)
    if not text or text.startswith(_SKIP_TITLE_PREFIXES):
        return ""
    return text


TAIL_BYTES = 131072  # bytes scanned from EOF for the latest aiTitle (~128 KiB)


def _last_aititle(path: str) -> str:
    """Last `aiTitle` in the file's final TAIL_BYTES, or '' if none/unreadable.

    Claude Code re-emits the session title as `{"type":"ai-title",...}` lines
    throughout the transcript; the last one reflects the current title
    (including a `/rename`). Reading only the tail keeps cost bounded on large
    transcripts.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > TAIL_BYTES:
                f.seek(size - TAIL_BYTES)
                f.readline()  # drop the partial first line after the seek
            data = f.read()
    except OSError:
        return ""
    title = ""
    for raw in data.split(b"\n"):
        raw = raw.strip()
        if not raw or b'"ai-title"' not in raw:  # cheap prefilter before JSON
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "ai-title" and obj.get("aiTitle"):
            title = str(obj["aiTitle"]).strip()[:120]
    return title


HEAD_LINES = 200  # transcript head scanned for cwd + the fallback title


def _scan_file(path: str) -> SessionInfo | None:
    """Read a transcript to learn its workspace and best title.

    Title precedence: last ``aiTitle`` (Claude Code auto-title / ``/rename``) →
    cleaned first user message → "(no summary)". Returns None for files that
    carry no ``cwd`` (not a resumable session).
    """
    sid = os.path.splitext(os.path.basename(path))[0]
    cwd, fallback = "", ""
    try:
        with open(path, "r", errors="replace") as f:
            # cwd + the fallback title live near the top; cap the head scan so
            # one giant transcript can't stall the (event-loop) caller.
            for lineno, line in enumerate(f):
                if lineno >= HEAD_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not cwd and obj.get("cwd"):
                    cwd = obj["cwd"]
                if not fallback and obj.get("type") == "user":
                    fallback = _clean_user_title(
                        obj.get("message", {}).get("content"))
                if cwd and fallback:
                    break
    except OSError:
        return None
    if not cwd:
        return None
    title = _last_aititle(path) or fallback or "(no summary)"
    mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    return SessionInfo(sid, cwd, title, mtime.isoformat())


def list_sessions(root: str = PROJECTS_ROOT, within_days: int = 14,
                  workspace: str | None = None) -> list[SessionInfo]:
    """All resumable sessions modified within ``within_days``, newest first.

    Optionally restricted to a single ``workspace`` (absolute cwd).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    out: list[SessionInfo] = []
    for path in glob.glob(os.path.join(root, "*", "*.jsonl")):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            continue
        info = _scan_file(path)
        if info and (workspace is None or info.workspace == workspace):
            out.append(info)
    out.sort(key=lambda s: s.mtime_iso, reverse=True)
    return out


def list_workspaces(root: str = PROJECTS_ROOT, within_days: int = 14) -> list[dict]:
    """Workspaces that have at least one recent session, most-recent first."""
    agg: dict[str, dict] = {}
    for s in list_sessions(root, within_days):
        w = agg.setdefault(s.workspace, {
            "workspace": s.workspace,
            "label": os.path.basename(s.workspace.rstrip("/")) or s.workspace,
            "session_count": 0,
            "last_active": s.mtime_iso,
        })
        w["session_count"] += 1
        if s.mtime_iso > w["last_active"]:
            w["last_active"] = s.mtime_iso
    return sorted(agg.values(), key=lambda w: w["last_active"], reverse=True)
