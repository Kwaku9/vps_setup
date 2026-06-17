"""
title: CC Sessions
author: aicortex
description: Resume real VPS Claude Code sessions from OpenWebUI. Each workspace
    appears as a model; pick a recent session, then keep talking to its real
    transcript. Tool approvals surface as native confirmation dialogs.
version: 0.1.0
requirements: httpx
"""

# OpenWebUI Pipe (manifold). Talks to the `owui-coder` service on
# enterprise_network, which runs `claude --resume` on the VPS and streams the
# reply back as Server-Sent Events. No model logic lives here — only OpenWebUI
# wiring: list workspaces, run an in-chat session picker, relay the SSE stream,
# and turn `approval` frames into native confirmation dialogs.

import base64
import json

import httpx
from pydantic import BaseModel, Field


def _enc(workspace: str) -> str:
    return base64.urlsafe_b64encode(workspace.encode()).decode().rstrip("=")


def _dec(pipe_id: str) -> str:
    pad = "=" * (-len(pipe_id) % 4)
    return base64.urlsafe_b64decode(pipe_id + pad).decode()


class Pipe:
    class Valves(BaseModel):
        OWUI_CODER_URL: str = Field(
            default="http://owui-coder:7557",
            description="owui-coder service base URL (enterprise_network)")
        OWUI_CODER_TOKEN: str = Field(
            default="", description="Bearer token for owui-coder")

    def __init__(self):
        self.valves = self.Valves()

    # --- helpers -----------------------------------------------------------
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.valves.OWUI_CODER_TOKEN}"}

    def _url(self, path: str) -> str:
        return f"{self.valves.OWUI_CODER_URL}{path}"

    # --- model list --------------------------------------------------------
    def pipes(self) -> list[dict]:
        try:
            r = httpx.get(self._url("/coder/sessions?workspaces_only=1"),
                          headers=self._headers(), timeout=10)
            r.raise_for_status()
            workspaces = r.json().get("workspaces", [])
        except Exception as e:
            return [{"id": "error", "name": f"CC Sessions (unreachable: {e})"}]
        return [{"id": _enc(w["workspace"]),
                 "name": f"CC: {w['label']} ({w['session_count']})"}
                for w in workspaces]

    # --- main turn ---------------------------------------------------------
    async def pipe(self, body: dict, __user__: dict = None,
                   __event_emitter__=None, __event_call__=None,
                   __metadata__: dict = None):
        model = body.get("model", "")
        pipe_id = model.split(".", 1)[-1]
        try:
            workspace = _dec(pipe_id)
        except Exception:
            yield "Could not resolve workspace from model id."
            return

        chat_id = (__metadata__ or {}).get("chat_id", "") or "owui"
        messages = body.get("messages", [])
        msg = (messages[-1].get("content", "") if messages else "").strip()

        async with httpx.AsyncClient(timeout=None) as client:
            # /new — start a fresh session for this chat
            if msg == "/new":
                await client.post(self._url("/coder/bind"), headers=self._headers(),
                                  json={"owui_chat_id": chat_id, "workspace": workspace,
                                        "session_id": None})
                yield "🆕 Fresh session started — send your next message."
                return

            bound = (await client.get(
                self._url("/coder/binding"), headers=self._headers(),
                params={"owui_chat_id": chat_id})).json()

            # session picker: unbound, or explicit /sessions
            if msg == "/sessions" or not bound.get("bound"):
                # a bare number selects from the current list
                if msg.isdigit():
                    sessions = (await client.get(
                        self._url("/coder/sessions"), headers=self._headers(),
                        params={"workspace": workspace})).json().get("sessions", [])
                    idx = int(msg) - 1
                    if 0 <= idx < len(sessions):
                        chosen = sessions[idx]
                        await client.post(
                            self._url("/coder/bind"), headers=self._headers(),
                            json={"owui_chat_id": chat_id, "workspace": workspace,
                                  "session_id": chosen["session_id"]})
                        yield (f"🔗 Bound to **{chosen['summary']}**\n\n"
                               "Send your message to continue this session.")
                        return
                    yield f"No session #{msg}. Send /sessions to re-list."
                    return
                async for chunk in self._render_menu(client, workspace):
                    yield chunk
                return

            # bound — stream a resumed turn
            async for chunk in self._stream_turn(client, chat_id, msg,
                                                  __event_call__):
                yield chunk

    async def _render_menu(self, client, workspace):
        sessions = (await client.get(
            self._url("/coder/sessions"), headers=self._headers(),
            params={"workspace": workspace})).json().get("sessions", [])
        if not sessions:
            yield "No recent sessions in this workspace. Send /new to start one."
            return
        lines = ["**Recent sessions** — reply with a number to resume:\n"]
        for i, s in enumerate(sessions[:20], 1):
            lines.append(f"{i}. {s['summary']}  ·  _{s['mtime_iso'][:16]}_")
        lines.append("\n_/new_ for a fresh session.")
        yield "\n".join(lines)

    async def _stream_turn(self, client, chat_id, prompt, event_call):
        async with client.stream(
                "POST", self._url("/coder/stream"), headers=self._headers(),
                json={"owui_chat_id": chat_id, "prompt": prompt}) as resp:
            event, data = None, None
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    data = line[6:]
                elif line == "":  # end of one SSE frame
                    async for out in self._handle_frame(event, data, client,
                                                        event_call):
                        yield out
                    event, data = None, None

    async def _handle_frame(self, event, data, client, event_call):
        if not event:
            return
        payload = json.loads(data) if data else {}
        if event == "text" or event == "result":
            text = payload.get("text", "")
            if text:
                yield text + "\n"
        elif event == "tool_use":
            yield f"\n🔧 `{payload.get('text')}` {payload.get('detail', '')}\n"
        elif event == "approval":
            approved = False
            if event_call:
                resp = await event_call({
                    "type": "confirmation",
                    "data": {"title": f"Approve {payload.get('tool')}?",
                             "message": payload.get("summary", "")}})
                approved = bool(resp)
            decision = "approved" if approved else "denied"
            await client.post(self._url("/coder/approve"), headers=self._headers(),
                              json={"approval_id": payload["approval_id"],
                                    "decision": decision})
            yield f"\n_{'✅ approved' if approved else '🚫 denied'}_\n"
        elif event == "done":
            code = payload.get("exit_code")
            if code not in (0, None):
                yield f"\n⚠ exited {code}\n{payload.get('stderr', '')}\n"
