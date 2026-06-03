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
