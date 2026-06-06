#!/usr/bin/env python3
"""Stand-in for the `claude` CLI in tests.

Ignores its args and prints a canned `--output-format stream-json` sequence:
an init event (with a session id), an assistant text block, an assistant
tool_use (Bash), then a result. Used by setting CLAUDE_CLI_PATH to this file.

If FAKE_CLAUDE_APPROVAL_URL is set, it POSTs a /request_approval before the
tool_use and polls /get_approval_status until the decision is non-pending —
mimicking the real PreToolUse hook so the SSE approval round-trip is exercised.
"""
import json
import os
import sys
import time
import urllib.request

SESSION_ID = os.environ.get("FAKE_CLAUDE_SESSION_ID", "fake-session-1")


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _post(url, payload, token):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _get(url, token):
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def maybe_request_approval():
    base = os.environ.get("FAKE_CLAUDE_APPROVAL_URL")
    if not base:
        return
    token = os.environ.get("TELEGRAM_GATEWAY_TOKEN", "")
    chat_id = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
    resp = _post(f"{base}/request_approval",
                 {"chat_id": chat_id, "prompt_text": "Run Bash?",
                  "metadata": {"tool_name": "Bash"}}, token)
    aid = resp["approval_id"]
    for _ in range(50):
        status = _get(f"{base}/get_approval_status?approval_id={aid}", token)
        if status.get("status") not in (None, "pending"):
            break
        time.sleep(0.05)


def main():
    emit({"type": "system", "subtype": "init", "session_id": SESSION_ID})
    emit({"type": "assistant",
          "message": {"content": [{"type": "text", "text": "Working on it"}]}})
    maybe_request_approval()
    emit({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}}]}})
    emit({"type": "result", "result": "done"})


if __name__ == "__main__":
    main()
