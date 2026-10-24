#!/usr/bin/env python3
"""Nonblocking Fedora session observer + narrowly scoped OPS reply dispatcher.

No CLI hooks or terminal injection. File offsets advance only after OPS commits
the batch. Credentials come from systemd's decrypted runtime credential dir.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import socket
import sqlite3
import time
import urllib.request
from pathlib import Path
from uuid import UUID

from websockets.sync.client import unix_connect

LOG = logging.getLogger("ops-session-bridge")
TRANSCRIPT_TYPES = {"message", "function_call", "custom_tool_call",
                    "function_call_output", "custom_tool_call_output"}


class Codex:
    def __init__(self, home):
        self.path = home / ".codex/app-server-control/app-server-control.sock"
        self.ws = None
        self.sequence = 0

    def close(self):
        if self.ws:
            self.ws.close()
        self.ws = None

    def connect(self):
        if self.ws:
            return
        self.ws = unix_connect(str(self.path), uri="ws://localhost", open_timeout=3)
        self.rpc("initialize", {"clientInfo": {"name": "ops_dashboard", "version": "0.1.0"},
                                "capabilities": {"experimentalApi": True}})
        self.ws.send('{"method":"initialized"}')

    def rpc(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.ws.send(json.dumps({"id": request_id, "method": method, "params": params}))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            message = json.loads(self.ws.recv(timeout=max(.1, deadline - time.monotonic())))
            if message.get("id") != request_id:
                continue  # never answer approval requests on behalf of the desktop client
            if "error" in message:
                raise RuntimeError("Codex rejected " + method)
            return message["result"]
        raise TimeoutError("Codex RPC timed out")


def valid_uuid(value):
    return str(UUID(str(value)))


def claude_sessions(home):
    found = {}
    registry = home / ".claude/sessions"
    for file in registry.glob("*.json"):
        try:
            record = json.loads(file.read_text())
            pid = int(record["pid"])
            os.kill(pid, 0)
            # Protect against a stale registry file and a recycled process ID.
            ticks = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
            if record.get("procStart") and str(record["procStart"]) != ticks:
                continue
            sid = valid_uuid(record["sessionId"])
            cwd = record["cwd"]
            directory = "".join(c if c.isalnum() else "-" for c in cwd)
            transcript = home / ".claude/projects" / directory / f"{sid}.jsonl"
            if not transcript.is_file():
                # Claude's directory encoding differs for Unicode/punctuation across versions.
                transcript = next((home / ".claude/projects").glob(f"*/{sid}.jsonl"), None)
            address = record.get("messagingSocketPath")
            state = record.get("status", "idle")
            found[sid] = {"session_uuid": sid, "agent_kind": "claude",
                          "name": record.get("name", "Claude Code"), "cwd": cwd,
                          "state": "running" if state in ("working", "running", "busy") else
                                   "waiting_input" if state in ("blocked", "waiting", "waiting_input") else "idle",
                          "input_available": bool(address and Path(address).exists()),
                          "_path": transcript, "_socket": address, "_pid": pid}
        except (OSError, ValueError, KeyError, StopIteration):
            continue
    return found


def locked_threads(home):
    """TUI clients can own a writer lock without loading into the shared daemon."""
    ids = []
    for file in (home / ".codex/thread-writer-locks").glob("*.lock"):
        try:
            sid = valid_uuid(file.stem)
            with file.open("rb") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    ids.append(sid)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
        except (OSError, ValueError):
            continue
    return ids


def codex_sessions(home, codex):
    codex.connect()
    ids = set(locked_threads(home))
    cursor = None
    while True:
        response = codex.rpc("thread/loaded/list", {"cursor": cursor, "limit": 100})
        ids.update(response["data"])
        cursor = response.get("nextCursor")
        if not cursor:
            break
    found = {}
    for sid in sorted(ids):
        record = codex.rpc("thread/read", {"threadId": sid, "includeTurns": False})["thread"]
        source = record.get("source")
        # Subagent histories are included as activity in their parent; list roots only.
        if isinstance(source, dict) and any("subAgent" in k or "subagent" in k for k in source):
            continue
        status = record.get("status", {})
        active = status.get("type") == "active"
        flags = status.get("activeFlags", [])
        found[sid] = {"session_uuid": valid_uuid(sid), "agent_kind": "codex",
                      "name": record.get("name") or "Codex", "cwd": record["cwd"],
                      "state": "waiting_input" if any("waiting" in f.lower() for f in flags) else
                               "running" if active else "idle", "input_available": not record.get("ephemeral", False),
                      "_path": Path(record["path"]) if record.get("path") else None}
    return found


def codex_line(raw, sid, seq, model):
    """Normalize finalized Codex items with the same UUIDs as nightly archival."""
    record = json.loads(raw)
    payload = record.get("payload") or {}
    if record.get("type") == "turn_context":
        return None, seq, payload.get("model") or model
    if record.get("type") != "response_item" or payload.get("type") not in TRANSCRIPT_TYPES:
        return None, seq, model
    kind = payload["type"]
    if kind == "message":
        role = payload.get("role", "assistant")
        if role == "developer":
            role = "user"
        content = payload.get("content", [])
    else:
        role = "user" if kind.endswith("output") else "assistant"
        content = [payload]
    message = {"sessionId": sid, "uuid": f"codex-{sid}-{seq}",
               "type": "user" if role == "user" else "assistant",
               "timestamp": record.get("timestamp"),
               "message": {"role": role, "content": content, "model": model}}
    return json.dumps(message, ensure_ascii=False), seq + 1, model


class Store:
    def __init__(self, path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS offsets(path TEXT PRIMARY KEY, inode INTEGER, offset INTEGER,
                                             sequence INTEGER, model TEXT);
          CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, status TEXT, detail TEXT,
                                              acknowledged INTEGER DEFAULT 0);
        """)

    def tail(self, session, budget):
        path = session.get("_path")
        if not path or not path.is_file():
            return [], None, budget
        stat = path.stat()
        saved = self.db.execute("SELECT inode,offset,sequence,model FROM offsets WHERE path=?",
                                (str(path),)).fetchone()
        offset, seq, model = (saved[1], saved[2], saved[3]) if saved and saved[0] == stat.st_ino and saved[1] <= stat.st_size else (0, 0, None)
        lines = []
        with path.open("rb") as file:
            file.seek(offset)
            while len(lines) < 500 and budget > 1000:
                before = file.tell()
                raw = file.readline()
                if not raw or not raw.endswith(b"\n"):
                    break  # never acknowledge a partially written JSONL record
                next_seq, next_model = seq, model
                try:
                    text = raw.decode("utf-8")
                    if session["agent_kind"] == "codex":
                        text, next_seq, next_model = codex_line(text, session["session_uuid"], seq, model)
                    else:
                        record = json.loads(text)
                        # Auxiliary snapshots do not belong in the transcript feed.
                        if record.get("type") not in ("user", "assistant") or record.get("isSidechain"):
                            text = None
                        else:
                            next_model = (record.get("message") or {}).get("model") or model
                    cost = len(json.dumps(text, ensure_ascii=False).encode()) if text else 0
                    if cost > budget:
                        file.seek(before)
                        break
                    if text:
                        lines.append(text)
                    budget -= cost
                    seq, model, offset = next_seq, next_model, file.tell()
                except (ValueError, UnicodeError, AttributeError):
                    LOG.warning("Skipping malformed finalized record for %s", session["session_uuid"])
                    offset = file.tell()
        session["model"] = model
        return lines, (str(path), stat.st_ino, offset, seq, model), budget

    def commit_offsets(self, rows):
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO offsets VALUES(?,?,?,?,?)", rows)

    def receipt(self, request_id, status, detail):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO receipts(id,status,detail) VALUES(?,?,?)",
                            (request_id, status, detail))


def post(base_url, token, path, payload):
    data = json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data,
                                     headers={"Authorization": "Bearer " + token,
                                              "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def send_claude(session, text, request_id):
    # Deliberately omit a peer permission-class assertion and auth token. The
    # session applies its usual inbound policy; this bridge cannot claim to be
    # the session's own child and cannot grant approval or execute slash commands.
    current = claude_sessions(Path.home()).get(session["session_uuid"])
    if not current or current.get("_pid") != session.get("_pid"):
        raise RuntimeError("Claude session disconnected")
    frame = {"type": "user", "uuid": request_id, "msg_id": request_id,
             "from": "ops-dashboard", "message": {"role": "user", "content": text}}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(current["_socket"])
        client.sendall((json.dumps(frame, ensure_ascii=False) + "\n").encode())
    return "Posted to Claude inbox. Inbound settings may require acceptance in the terminal."


def dispatch(command, sessions, codex, store):
    request_id = str(command["id"])
    if store.db.execute("SELECT id FROM receipts WHERE id=?", (request_id,)).fetchone():
        return  # at most one transport attempt even after reconnect/restart
    session = sessions.get(command["session_uuid"])
    if not session or not session["input_available"]:
        store.receipt(request_id, "failed", "The desktop session disconnected before delivery.")
        return
    # Persist before crossing the non-transactional native CLI boundary.
    store.receipt(request_id, "uncertain", "Delivery interrupted. Check the desktop session before sending again.")
    try:
        if session["agent_kind"] == "claude":
            detail = send_claude(session, command["text"], request_id)
        else:
            codex.connect()
            codex.rpc("thread/queue/add", {"threadId": session["session_uuid"],
                       "clientUserMessageId": request_id,
                       "input": [{"type": "text", "text": command["text"]}]})
            detail = "Added to the existing Codex session queue for its next turn."
        store.receipt(request_id, "delivered", detail)
    except (ConnectionError, FileNotFoundError):
        store.receipt(request_id, "failed", "The session could not be reached.")
    except Exception:  # noqa: BLE001 — native write outcome can be ambiguous; never repeat it
        # No prompt, credential, RPC response, or raw exception text in journals.
        LOG.warning("Delivery uncertain for request %s", request_id)


def step(home, codex, store, base_url, token, discover=False):
    sessions = claude_sessions(home)
    complete = True
    try:
        sessions.update(codex_sessions(home, codex))
    except Exception:  # noqa: BLE001 — discovery failure must not end other desktop sessions
        codex.close()
        # A missing daemon is normal; a present socket with a failed read is not.
        complete = not codex.path.exists() and not locked_threads(home)
    if discover:
        return [{k: v for k, v in s.items() if not k.startswith("_")} for s in sessions.values()]
    offsets = []
    outgoing = []
    budget = 6 * 1024 * 1024
    for session in list(sessions.values())[:32]:
        lines, checkpoint, budget = store.tail(session, budget)
        if checkpoint:
            offsets.append((session["session_uuid"], checkpoint))
        outgoing.append({**{k: v for k, v in session.items() if not k.startswith("_")},
                         "transcript_delta": lines})
    response = post(base_url, token, "/api/workstations/sync",
                    {"sessions": outgoing, "discovery_complete": complete and len(sessions) <= 32})
    accepted = set(response["accepted"])
    store.commit_offsets([row for sid, row in offsets if sid in accepted])
    for command in response.get("commands", []):
        dispatch(command, sessions, codex, store)
    for rid, status, detail in store.db.execute("SELECT id,status,detail FROM receipts WHERE acknowledged=0").fetchall():
        post(base_url, token, "/api/workstations/result", {"id": rid, "status": status, "detail": detail})
        with store.db:
            store.db.execute("UPDATE receipts SET acknowledged=1 WHERE id=?", (rid,))
    LOG.info("Connected: %d desktop sessions, %d transcript records", len(outgoing),
             sum(len(s["transcript_delta"]) for s in outgoing))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discover", action="store_true", help="read-only discovery; no token or network")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--url", default=os.environ.get("OPS_BRIDGE_URL"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    home = Path.home()
    codex = Codex(home)
    if args.discover:
        print(json.dumps(step(home, codex, None, None, None, discover=True), indent=2))
        codex.close()
        return
    if not args.url:
        parser.error("Set OPS_BRIDGE_URL or pass --url.")
    credential_dir = Path(os.environ["CREDENTIALS_DIRECTORY"])
    token = (credential_dir / "ops-session-token").read_text().strip()
    store = Store(Path(os.environ.get("STATE_DIRECTORY", home / ".local/state/ops-session-bridge")) / "state.sqlite3")
    failures = 0
    try:
        while True:
            try:
                step(home, codex, store, args.url, token)
                failures = 0
            except Exception as exc:  # noqa: BLE001 — reconnect without leaking payload/credential in logs
                failures += 1
                LOG.warning("Bridge unavailable (%s); retaining transcript offsets", type(exc).__name__)
                if args.once:
                    raise SystemExit(1) from None
            if args.once:
                break
            time.sleep(min(30, 5 * 2 ** min(failures, 3)))
    finally:
        codex.close()


if __name__ == "__main__":
    main()
