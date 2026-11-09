"""Live ingest path redacts with the same redact.py/registry/key as the nightly ingest, or stores nothing."""
import asyncio
import hashlib
import hmac
import json
import shutil
from pathlib import Path

import pytest

from ops_dashboard.api.routers import ingest
from ops_dashboard.sessions import redaction

REPO = Path(__file__).resolve().parents[5]
KEY = b"test-hmac-key-not-a-real-one-000"
SECRET = "Zq7pLm2xVb9KwT4r"  # shapeless: only the registry can catch it


def make_dir(tmp_path, key=KEY, entries=True):
    shutil.copy(REPO / "tools/redaction/redact.py", tmp_path / "redact.py")
    h = hmac.new(KEY, SECRET.encode(), hashlib.sha256).hexdigest()
    reg = {"key_id": hashlib.sha256(KEY).hexdigest()[:12],
           "entries": {h: {"label": "test_secret", "len": len(SECRET), "entropy": 4.0}} if entries else {}}
    (tmp_path / "secret-registry.json").write_text(json.dumps(reg))
    (tmp_path / ".redaction-hmac.key").write_bytes(key)
    return tmp_path


def parsed():
    return {"session_uuid": "s1",
            "messages": [{"uuid": "m1", "type": "user", "content_text": f"export PGPASSWORD={SECRET}",
                          "content_json": [{"type": "text", "text": f"pw {SECRET}"}], "model": "x"}],
            "tool_calls": [{"message_uuid": "m1", "tool_name": "Bash",
                            "input_json": {"command": f"psql --password={SECRET}"},
                            "result_text": f"connected with {SECRET}"}]}


def test_loads_real_redactor_with_registry(tmp_path):
    r = redaction.load_redactor(make_dir(tmp_path))
    assert r is not None and r.entries


@pytest.mark.parametrize("breakage", ["missing_dir", "wrong_key", "empty_registry", "no_module"])
def test_fails_closed(tmp_path, breakage):
    d = tmp_path / "r"
    d.mkdir()
    if breakage == "missing_dir":
        d = tmp_path / "nope"
    elif breakage == "wrong_key":
        make_dir(d, key=b"some-other-key-0000000000000000")
    elif breakage == "empty_registry":
        make_dir(d, entries=False)
    elif breakage == "no_module":
        make_dir(d)
        (d / "redact.py").unlink()
    assert redaction.load_redactor(d) is None


def test_every_content_field_is_redacted(tmp_path):
    out = redaction.redact_parsed(parsed(), redaction.load_redactor(make_dir(tmp_path)))
    blob = json.dumps(out)
    assert SECRET not in blob
    assert blob.count("test_secret") == 4  # content_text, content_json, input_json, result_text
    assert out["messages"][0]["model"] == "x" and out["tool_calls"][0]["tool_name"] == "Bash"


def test_prepare_without_redactor_withholds_content(monkeypatch):
    monkeypatch.setattr(redaction, "get_redactor", lambda: None)
    out = redaction.prepare(parsed())
    assert out["messages"] == [] and out["tool_calls"] == [] and out["session_uuid"] == "s1"


class _Pool:
    class _Conn:
        def transaction(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    def acquire(self):
        return self._Conn()


def _run_ingest(monkeypatch):
    seen = {}

    async def fake_upsert(conn, payload, p):
        seen["parsed"] = p
        return {"session_uuid": p["session_uuid"]}

    monkeypatch.setattr(ingest, "upsert_event", fake_upsert)
    monkeypatch.setattr(ingest, "parse_lines", lambda lines, source: parsed())
    asyncio.run(ingest.handle_ingest(_Pool(), {"session_uuid": "s1", "event_type": "Stop"}))
    return seen["parsed"]


def test_handle_ingest_writes_only_redacted_content(tmp_path, monkeypatch):
    r = redaction.load_redactor(make_dir(tmp_path))
    monkeypatch.setattr(redaction, "get_redactor", lambda: r)
    written = _run_ingest(monkeypatch)
    assert SECRET not in json.dumps(written) and written["messages"]


def test_handle_ingest_still_updates_session_when_redaction_unavailable(monkeypatch):
    monkeypatch.setattr(redaction, "get_redactor", lambda: None)
    written = _run_ingest(monkeypatch)
    assert written["session_uuid"] == "s1" and written["messages"] == [] and written["tool_calls"] == []


def test_get_redactor_retries_at_most_once_per_interval(monkeypatch):
    calls = []
    monkeypatch.setattr(redaction, "_redactor", None)
    monkeypatch.setattr(redaction, "_last_failure", 0.0)
    monkeypatch.setattr(redaction, "load_redactor", lambda: calls.append(1))
    redaction.get_redactor(); redaction.get_redactor(); redaction.get_redactor()
    assert len(calls) == 1
