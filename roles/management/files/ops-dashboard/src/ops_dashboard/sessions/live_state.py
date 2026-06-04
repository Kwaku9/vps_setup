"""Pure mapping from a Claude Code hook event to live session state."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LiveState:
    live_status: str            # running | waiting_input | idle | ended
    needs_input: bool
    current_stage: str | None


def derive_live_state(
    event_type: str,
    tool_name: str | None = None,
    prev_needs_input: bool = False,
) -> LiveState:
    if event_type == "SessionStart":
        return LiveState("running", False, "started")
    if event_type == "UserPromptSubmit":
        return LiveState("running", False, "working")
    if event_type == "PreToolUse":
        return LiveState("running", False, tool_name or "tool")
    if event_type == "PostToolUse":
        return LiveState("running", False, f"{tool_name or 'tool'} ✓")
    if event_type == "Notification":
        return LiveState("waiting_input", True, "waiting for input")
    if event_type == "Stop":
        # Turn ended; keep needs_input only if a Notification left it outstanding.
        return LiveState("waiting_input", prev_needs_input, "turn complete")
    if event_type == "SubagentStop":
        return LiveState("running", prev_needs_input, "subagent finished")
    if event_type == "SessionEnd":
        return LiveState("ended", False, "ended")
    return LiveState("running", prev_needs_input, None)
