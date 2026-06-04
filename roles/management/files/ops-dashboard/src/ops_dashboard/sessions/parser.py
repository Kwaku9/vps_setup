"""Vendored JSONL parser for real-time transcript deltas.

Mirrors tools/ingest-sessions.py. Parity is enforced by tests/test_parser.py.
If you change parsing here, mirror it in tools/ingest-sessions.py (or vice versa).
"""
from __future__ import annotations

import json
from pathlib import Path

# --- ported verbatim from tools/ingest-sessions.py (pure helpers) ---

LANG_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".jsx": "javascript", ".json": "json", ".yml": "yaml", ".yaml": "yaml",
    ".md": "markdown", ".html": "html", ".css": "css", ".scss": "scss",
    ".sh": "shell", ".bash": "shell", ".sql": "sql", ".go": "go",
    ".rs": "rust", ".java": "java", ".rb": "ruby", ".php": "php",
    ".xml": "xml", ".toml": "toml", ".ini": "ini", ".conf": "config",
    ".dockerfile": "dockerfile", ".tf": "terraform", ".j2": "jinja2",
    ".vue": "vue", ".svelte": "svelte", ".graphql": "graphql",
}


def sanitize_text(text):
    """Remove null bytes and other problematic characters for PostgreSQL."""
    if text is None:
        return None
    if isinstance(text, str):
        return text.replace("\x00", "")
    return text


def sanitize_json(obj):
    """Recursively remove null bytes from JSON-serializable objects."""
    if isinstance(obj, str):
        return obj.replace("\x00", "")
    elif isinstance(obj, dict):
        return {sanitize_json(k): sanitize_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_json(item) for item in obj]
    return obj


def infer_language(file_path):
    """Infer programming language from file extension."""
    if not file_path:
        return None
    ext = Path(file_path).suffix.lower()
    if ext in LANG_MAP:
        return LANG_MAP[ext]
    name = Path(file_path).name.lower()
    if name == "dockerfile":
        return "dockerfile"
    if name in ("makefile", "gnumakefile"):
        return "makefile"
    return None


def extract_text_content(content):
    """Extract plain text from message content (can be string or array)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(texts) if texts else None
    return None


def parse_lines(lines: list[str], source: str) -> dict:
    """Parse raw JSONL line strings into normalized session/message/tool_call dicts.

    Returns: {"session_uuid", "messages": [...], "tool_calls": [...]}
    """
    session_uuid = None
    messages = []
    tool_calls = []
    seq = 0
    tc_seq = 0
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        sid = rec.get("sessionId") or rec.get("session_id")
        if sid:
            session_uuid = sid
        rtype = rec.get("type")
        if rtype not in ("user", "assistant"):
            continue
        msg = rec.get("message") or {}
        usage = msg.get("usage") or {}
        content = msg.get("content")
        seq += 1
        messages.append({
            "uuid": rec.get("uuid"),
            "parent_uuid": rec.get("parentUuid"),
            "type": rtype,
            "role": msg.get("role", rtype),
            "content_text": sanitize_text(extract_text_content(content)),
            "content_json": sanitize_json(content) if isinstance(content, list) else None,
            "model": msg.get("model"),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
            "is_sidechain": bool(rec.get("isSidechain", False)),
            "cwd": rec.get("cwd"),
            "timestamp": rec.get("timestamp"),
            "sequence_num": seq,
        })
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tc_seq += 1
                    tool_calls.append({
                        "message_uuid": rec.get("uuid"),
                        "tool_use_id": block.get("id"),
                        "tool_name": block.get("name"),
                        "input_json": block.get("input"),
                        "result_text": None,
                        "status": "pending",
                        "timestamp": rec.get("timestamp"),
                        "sequence_num": tc_seq,
                    })
    return {"session_uuid": session_uuid, "messages": messages, "tool_calls": tool_calls}
