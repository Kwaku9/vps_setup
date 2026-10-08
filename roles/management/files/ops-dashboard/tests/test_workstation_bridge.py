"""Reliable offsets, archive-compatible Codex identities, and at-most-once dispatch."""
import importlib.util
import json
from pathlib import Path

import pytest

bridge_path = Path(__file__).parents[5] / "roles/workstation/files/bin/ops-session-bridge.py"
spec = importlib.util.spec_from_file_location("ops_bridge", bridge_path)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

SID = "12ebe03e-3ea9-4c97-9efc-9bfbad839f7d"


def test_offsets_advance_only_on_ack_and_partial_record_is_retained(tmp_path):
    file = tmp_path / "session.jsonl"
    first = json.dumps({"type": "assistant", "uuid": "first", "sessionId": SID,
                        "message": {"role": "assistant", "content": "Complete"}})
    second = json.dumps({"type": "user", "uuid": "second", "sessionId": SID,
                         "message": {"role": "user", "content": "Complete too"}})
    file.write_text(first + "\n" + second[:20])
    store = bridge.Store(tmp_path / "state.sqlite3")
    session = {"agent_kind": "claude", "session_uuid": SID, "_path": file}
    lines, checkpoint, _ = store.tail(session, 100000)
    assert len(lines) == 1
    assert store.tail(session, 100000)[0] == lines  # failed upload is retried
    store.commit_offsets([checkpoint])
    assert store.tail(session, 100000)[0] == []
    with file.open("a") as out:
        out.write(second[20:] + "\n")
    assert json.loads(store.tail(session, 100000)[0][0])["uuid"] == "second"


def test_codex_items_keep_archive_uuids_and_full_structured_output(tmp_path):
    file = tmp_path / "codex.jsonl"
    records = [
        {"type": "session_meta", "payload": {"id": SID}},
        {"type": "turn_context", "payload": {"model": "test-model"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                              "content": [{"type": "output_text", "text": "## Status\nAll done"}]}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "call-1", "arguments": '{"cmd":"pwd"}'}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call-1", "output": "large output\n" * 12000}},
    ]
    file.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    store = bridge.Store(tmp_path / "state.sqlite3")
    session = {"agent_kind": "codex", "session_uuid": SID, "_path": file}
    lines, checkpoint, _ = store.tail(session, 1000000)
    messages = list(map(json.loads, lines))
    assert [m["uuid"] for m in messages] == [f"codex-{SID}-{i}" for i in range(3)]
    assert messages[2]["message"]["content"][0]["output"] == records[-1]["payload"]["output"]
    assert session["model"] == "test-model"
    store.commit_offsets([checkpoint])
    assert store.tail(session, 1000000)[0] == []


@pytest.mark.parametrize("fail", [False, True])
def test_dispatch_does_not_repeat_ambiguous_or_successful_native_send(tmp_path, fail):
    store = bridge.Store(tmp_path / "state.sqlite3")
    calls = []

    class Codex:
        def connect(self):
            pass

        def rpc(self, method, params):
            calls.append((method, params))
            assert store.db.execute("SELECT status FROM receipts").fetchone()[0] == "uncertain"
            if fail:
                raise TimeoutError()
            return {"queuedSubmission": {"id": "test"}}

    command = {"id": "queued-id", "session_uuid": SID, "text": "Keep going"}
    sessions = {SID: {"session_uuid": SID, "agent_kind": "codex", "input_available": True}}
    bridge.dispatch(command, sessions, Codex(), store)
    bridge.dispatch(command, sessions, Codex(), store)
    assert len(calls) == 1
    assert calls[0][1]["clientUserMessageId"] == command["id"]
    assert store.db.execute("SELECT status FROM receipts").fetchone()[0] == ("uncertain" if fail else "delivered")


def test_stale_session_never_receives_input(tmp_path):
    store = bridge.Store(tmp_path / "state.sqlite3")
    bridge.dispatch({"id": "request", "session_uuid": SID, "text": "Hello"}, {}, None, store)
    assert store.db.execute("SELECT status FROM receipts").fetchone()[0] == "failed"
