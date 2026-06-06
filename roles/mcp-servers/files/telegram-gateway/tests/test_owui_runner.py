import os

from telegram_gateway import owui_runner

FAKE = os.path.join(os.path.dirname(__file__), "fake_claude.py")


async def _collect(monkeypatch, tmp_path, session_id=None):
    os.chmod(FAKE, 0o755)
    monkeypatch.setattr(owui_runner, "CLAUDE_CLI_PATH", FAKE)
    items = []
    async for item, code in owui_runner.run_coder_turn(
            "do it", str(tmp_path), session_id=session_id):
        items.append((item, code))
    return items


async def test_run_coder_turn_streams_items(monkeypatch, tmp_path):
    items = await _collect(monkeypatch, tmp_path)
    kinds = [it.kind for it, _ in items]
    assert "session" in kinds
    assert "text" in kinds
    assert "tool_use" in kinds
    assert "result" in kinds
    last_item, last_code = items[-1]
    assert last_item.kind == "_exit"
    assert last_code == 0
    session_item = next(it for it, _ in items if it.kind == "session")
    assert session_item.text == "fake-session-1"


async def test_workspace_lock_is_per_workspace():
    a1 = owui_runner.workspace_lock("/a")
    a2 = owui_runner.workspace_lock("/a")
    b = owui_runner.workspace_lock("/b")
    assert a1 is a2
    assert a1 is not b


async def test_approval_registry_roundtrip():
    q = owui_runner.register_run(123)
    assert owui_runner.push_approval(123, {"approval_id": 9}) is True
    assert (await q.get())["approval_id"] == 9
    assert owui_runner.push_approval(999, {"approval_id": 1}) is False
    owui_runner.unregister_run(123)
    assert owui_runner.push_approval(123, {"approval_id": 2}) is False
