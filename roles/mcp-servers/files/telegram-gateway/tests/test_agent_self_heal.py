"""Self-heal for stale Claude CLI sessions in the gateway path.

`claude --resume <id>` returns empty stdout + "No conversation found ..." on
stderr when the stored session can't be resumed from the gateway's cwd/project.
Without clearing the stored session id the chat is stuck forever (every message
re-resumes the dead session). _resolve_no_output detects that and signals a
reset — mirroring the self-heal coder.py already has.
"""
from telegram_gateway.agent import _resolve_no_output


def test_blocks_present_pass_through():
    blocks = [("text", "hello")]
    assert _resolve_no_output(blocks, "", True) == (blocks, False)


def test_no_conversation_found_with_session_triggers_reset():
    blocks, clear = _resolve_no_output(
        [], "No conversation found with session ID: abc-123", True)
    assert clear is True
    assert "reset" in blocks[0][1].lower()


def test_no_conversation_found_without_session_does_not_reset():
    blocks, clear = _resolve_no_output([], "No conversation found ...", False)
    assert clear is False
    assert blocks == [("text", "(No output from Claude CLI)")]


def test_other_empty_output_does_not_reset():
    blocks, clear = _resolve_no_output([], "some unrelated stderr noise", True)
    assert clear is False
    assert blocks == [("text", "(No output from Claude CLI)")]
