#!/usr/bin/env python3
"""Idempotently merge the live-session hook + env into a Claude settings.json.

Usage: merge-claude-settings.py <settings.json> <hook_command> [<env.json>]

- Adds the session-event hook to every lifecycle event WITHOUT removing any
  existing hook (e.g. the Telegram approval PreToolUse hook is preserved).
- Merges env keys from the optional env file into settings["env"].
- Refuses to overwrite a settings.json that exists but is not valid JSON
  (prints ERROR, exits 2) so it can never silently wipe an existing config.
- Prints CHANGED if it wrote, OK if nothing changed.
"""
import json
import os
import sys

EVENTS = [
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "Notification", "Stop", "SubagentStop", "SessionEnd",
]
EVENTS_WITH_MATCHER = {"PreToolUse", "PostToolUse"}
MARKER = "session-event-hook.js"


def load_required(path):
    """Load JSON; {} if absent/empty; abort if present-but-unparseable."""
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        text = f.read().strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"ERROR: {path} exists but is not valid JSON; refusing to overwrite",
              file=sys.stderr)
        sys.exit(2)


def main():
    settings_path = sys.argv[1]
    hook_cmd = sys.argv[2]
    env_path = sys.argv[3] if len(sys.argv) > 3 else None

    settings = load_required(settings_path)
    changed = False

    hooks = settings.setdefault("hooks", {})
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        already = any(
            MARKER in (h.get("command", "") or "")
            for g in groups
            for h in g.get("hooks", [])
        )
        if already:
            continue
        group = {"hooks": [{"type": "command", "command": hook_cmd}]}
        if event in EVENTS_WITH_MATCHER:
            group["matcher"] = "*"
        groups.append(group)
        changed = True

    if env_path and os.path.exists(env_path):
        env = load_required(env_path)
        senv = settings.setdefault("env", {})
        for k, v in env.items():
            if senv.get(k) != v:
                senv[k] = v
                changed = True

    if changed:
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        os.chmod(settings_path, 0o600)
        print("CHANGED")
    else:
        print("OK")


if __name__ == "__main__":
    main()
