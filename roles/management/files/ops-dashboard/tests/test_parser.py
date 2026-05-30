from pathlib import Path
from ops_dashboard.sessions.parser import parse_lines

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"


def test_parse_lines_extracts_messages_and_tools():
    lines = FIXTURE.read_text().splitlines()
    out = parse_lines(lines, source="vps")
    assert out["session_uuid"] == "11111111-1111-1111-1111-111111111111"
    assert len(out["messages"]) == 2
    assert out["messages"][0]["role"] == "user"
    assert out["messages"][0]["content_text"] == "run the tests"
    assert len(out["tool_calls"]) == 1
    tc = out["tool_calls"][0]
    assert tc["tool_name"] == "Bash"
    assert tc["tool_use_id"] == "tu1"
    assert tc["input_json"]["command"] == "pytest"
