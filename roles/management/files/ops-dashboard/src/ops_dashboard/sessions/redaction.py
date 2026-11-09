"""Credential redaction for the real-time ingest path.

The nightly ingest (tools/ingest-sessions.py) redacts every message before it
reaches sessions.messages. This live path used to write raw text, and because
every writer upserts with ON CONFLICT (session_id, uuid) DO NOTHING, the nightly
redacted copy of a message the live path wrote first was silently discarded -
so a credential typed into a live-tracked session stayed in Postgres for good,
then flowed on into recall.chunks and the Neo4j previews.

Same redactor, same registry, same key as the nightly ingest: the files are
deployed from the same repo sources (tools/redaction/) by the management role
and mounted read-only at OPS_REDACTION_DIR.

FAIL CLOSED: without a loaded registry the live path stores NO message content
(session live-state still updates, so the dashboard keeps working). That is
self-healing, not lossy: the nightly ingest inserts those messages itself,
redacted, because nothing from the live path is in the way of DO NOTHING.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DIR = "/opt/redaction"
RETRY_SECONDS = 60

_redactor = None
_last_failure = 0.0


def load_redactor(directory: str | os.PathLike | None = None):
    """Load redact.py + registry + HMAC key from `directory`. None unless the registry is live."""
    d = Path(directory or os.environ.get("OPS_REDACTION_DIR", DEFAULT_DIR))
    try:
        spec = importlib.util.spec_from_file_location("ops_live_redact", d / "redact.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        key = (d / ".redaction-hmac.key").read_bytes().strip()
        registry = json.loads((d / "secret-registry.json").read_text())
        redactor = mod.Redactor(registry, key)  # raises if the key does not match the registry
    except Exception as e:  # noqa: BLE001 - any failure means "do not store content"
        log.error("live ingest redaction unavailable (%s: %s); message content will NOT be stored "
                  "until it loads - the nightly ingest fills it in, redacted", type(e).__name__, e)
        return None
    if not redactor.entries:
        log.error("live ingest redaction loaded an EMPTY registry; message content will NOT be stored")
        return None
    return redactor


def get_redactor():
    """Cached redactor. After a failure, retry at most every RETRY_SECONDS (not per event)."""
    global _redactor, _last_failure
    if _redactor is None and time.monotonic() - _last_failure >= RETRY_SECONDS:
        _redactor = load_redactor()
        if _redactor is None:
            _last_failure = time.monotonic()
    return _redactor


def redact_parsed(parsed: dict, redactor) -> dict:
    """Pure: a copy of parse_lines() output with every content field redacted."""
    messages = [{**m,
                 "content_text": redactor.text(m.get("content_text")),
                 "content_json": redactor.json(m["content_json"]) if m.get("content_json") is not None else None}
                for m in parsed.get("messages", [])]
    tool_calls = [{**t,
                   "input_json": redactor.json(t["input_json"]) if t.get("input_json") is not None else None,
                   "result_text": redactor.text(t.get("result_text"))}
                  for t in parsed.get("tool_calls", [])]
    return {**parsed, "messages": messages, "tool_calls": tool_calls}


def withhold_content(parsed: dict) -> dict:
    """Pure: keep the session/live-state update, drop all content (fail-closed path)."""
    return {**parsed, "messages": [], "tool_calls": []}


def prepare(parsed: dict, redactor=None) -> dict:
    """What the live path may write: redacted content, or none at all."""
    r = redactor if redactor is not None else get_redactor()
    return redact_parsed(parsed, r) if r is not None else withhold_content(parsed)
