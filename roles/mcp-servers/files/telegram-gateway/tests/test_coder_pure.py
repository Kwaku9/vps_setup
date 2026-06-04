from telegram_gateway.coder import parse_stream_event, FeedItem


def test_init_event_yields_session_id():
    items = parse_stream_event({"type": "system", "subtype": "init",
                                "session_id": "abc-123"})
    assert items == [FeedItem(kind="session", text="abc-123")]


def test_assistant_text_block():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Working on it"}]}}
    assert parse_stream_event(ev) == [FeedItem(kind="text", text="Working on it")]


def test_assistant_tool_use_block():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "npm test"}}]}}
    items = parse_stream_event(ev)
    assert items[0].kind == "tool_use"
    assert items[0].text == "Bash"
    assert items[0].detail == "command: npm test"


def test_user_tool_result_block():
    ev = {"type": "user", "message": {"content": [
        {"type": "tool_result", "content": "12 passed"}]}}
    items = parse_stream_event(ev)
    assert items[0].kind == "tool_result"
    assert "12 passed" in items[0].text


def test_final_result_event():
    ev = {"type": "result", "result": "Done. 3 files changed."}
    assert parse_stream_event(ev) == [FeedItem(kind="result", text="Done. 3 files changed.")]


def test_unknown_event_ignored():
    assert parse_stream_event({"type": "system", "subtype": "other"}) == []


def test_user_tool_result_list_content():
    ev = {"type": "user", "message": {"content": [
        {"type": "tool_result", "content": [
            {"type": "text", "text": "line one"}, {"type": "text", "text": "line two"}]}]}}
    items = parse_stream_event(ev)
    assert items[0].kind == "tool_result"
    assert "line one" in items[0].text and "line two" in items[0].text


def test_malformed_blocks_do_not_raise():
    ev = {"type": "assistant", "message": {"content": ["notadict",
        {"type": "text", "text": "ok"}]}}
    assert parse_stream_event(ev) == [FeedItem(kind="text", text="ok")]


from telegram_gateway.coder import build_permission_prompt, decide_from_status


def test_build_permission_prompt_bash():
    txt = build_permission_prompt("Bash", {"command": "rm -rf build"})
    assert "Bash" in txt and "rm -rf build" in txt


def test_build_permission_prompt_write():
    txt = build_permission_prompt("Write", {"file_path": "/workspace/a.py"})
    assert "Write" in txt and "/workspace/a.py" in txt


def test_decide_approved():
    assert decide_from_status("approved") == {"behavior": "allow"}


def test_decide_denied():
    d = decide_from_status("denied")
    assert d["behavior"] == "deny" and d["message"]


def test_decide_expired():
    d = decide_from_status("expired")
    assert d["behavior"] == "deny" and "expire" in d["message"].lower()
