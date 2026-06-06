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


def _scan_file(path: str) -> SessionInfo | None:
    """Read a transcript far enough to learn its workspace and a summary.

    Returns None for files that carry no ``cwd`` (not a resumable session).
    """
    sid = os.path.splitext(os.path.basename(path))[0]
    cwd, summary = "", ""
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not cwd and obj.get("cwd"):
                    cwd = obj["cwd"]
                if not summary and obj.get("type") == "summary" and obj.get("summary"):
                    summary = str(obj["summary"])[:120]
                if not summary and obj.get("type") == "user":
                    content = obj.get("message", {}).get("content")
                    if isinstance(content, str) and content.strip():
                        summary = content.strip()[:120]
                if cwd and summary:
                    break
    except OSError:
        return None
    if not cwd:
        return None
    mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    return SessionInfo(sid, cwd, summary or "(no summary)", mtime.isoformat())


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
