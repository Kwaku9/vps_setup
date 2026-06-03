from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeedItem:
    """One unit of the progress feed derived from a stream-json event."""
    kind: str          # "session" | "text" | "tool_use" | "tool_result" | "result"
    text: str
    detail: str = ""   # tool input summary, for tool_use


def _summarize_input(tool_input: dict) -> str:
    """Compact one-line-ish summary of a tool's input for the feed."""
    if not isinstance(tool_input, dict):
        return str(tool_input)
    for key in ("command", "file_path", "path", "pattern", "query"):
        if key in tool_input:
            return f"{key}: {tool_input[key]}"
    return ", ".join(f"{k}: {v}" for k, v in list(tool_input.items())[:3])


def parse_stream_event(event: dict) -> list[FeedItem]:
    """Map a single `--output-format stream-json` event to feed items.

    Returns [] for events that produce no user-visible output.
    """
    etype = event.get("type")

    if etype == "system" and event.get("subtype") == "init":
        sid = event.get("session_id")
        return [FeedItem(kind="session", text=sid)] if sid else []

    if etype == "assistant":
        items: list[FeedItem] = []
        for block in event.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text" and block.get("text", "").strip():
                items.append(FeedItem(kind="text", text=block["text"].strip()))
            elif btype == "tool_use":
                items.append(FeedItem(
                    kind="tool_use",
                    text=block.get("name", "tool"),
                    detail=_summarize_input(block.get("input", {})),
                ))
        return items

    if etype == "user":
        items = []
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):  # content can be a block list
                    content = " ".join(
                        b.get("text", "") for b in content if isinstance(b, dict))
                items.append(FeedItem(kind="tool_result", text=str(content)))
        return items

    if etype == "result":
        return [FeedItem(kind="result", text=str(event.get("result", "")))]

    return []
