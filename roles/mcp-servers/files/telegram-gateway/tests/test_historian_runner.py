import inspect
from telegram_gateway import owui_runner


def test_run_coder_turn_accepts_historian_overrides():
    sig = inspect.signature(owui_runner.run_coder_turn)
    assert "mcp_config" in sig.parameters
    assert "append_system_prompt" in sig.parameters
    assert sig.parameters["mcp_config"].default is None
    assert sig.parameters["append_system_prompt"].default is None


def test_build_claude_args_threads_overrides():
    args = owui_runner._build_claude_args(
        prompt="when did I set up CrowdSec?", session_id=None,
        model="claude-opus-4-8",
        allowed_tools="Read,mcp__session-recall__search_sessions",
        mcp_config="/app/historian-mcp.json",
        append_system_prompt="You are the Historian.")
    assert "--mcp-config" in args and "/app/historian-mcp.json" in args
    assert "--append-system-prompt" in args and "You are the Historian." in args
    assert "--strict-mcp-config" in args


def test_build_claude_args_defaults_to_coder_config():
    from telegram_gateway.config import CODER_APPROVER_MCP_CONFIG
    args = owui_runner._build_claude_args(
        prompt="hi", session_id="abc", model="m", allowed_tools="Read")
    assert CODER_APPROVER_MCP_CONFIG in args
    assert "--append-system-prompt" not in args
    assert "--resume" in args and "abc" in args
