import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from telegram_gateway import owui_api, db, sessions, owui_runner
from telegram_gateway.sessions import SessionInfo


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(owui_api.router)
    return TestClient(app)


def test_sessions_workspaces_only(client, monkeypatch):
    monkeypatch.setattr(sessions, "list_workspaces",
                        lambda **k: [{"workspace": "/w", "label": "w",
                                      "session_count": 2, "last_active": "t"}])
    r = client.get("/coder/sessions?workspaces_only=1")
    assert r.status_code == 200
    assert r.json()["workspaces"][0]["label"] == "w"


def test_sessions_for_workspace(client, monkeypatch):
    monkeypatch.setattr(sessions, "list_sessions",
                        lambda **k: [SessionInfo("s1", "/w", "sum", "t")])
    r = client.get("/coder/sessions?workspace=/w")
    assert r.status_code == 200
    body = r.json()
    assert body["sessions"][0]["session_id"] == "s1"
    assert body["sessions"][0]["summary"] == "sum"


def test_binding_absent(client, monkeypatch):
    async def _none(_):
        return None
    monkeypatch.setattr(db, "get_owui_binding", _none)
    r = client.get("/coder/binding?owui_chat_id=c1")
    assert r.json() == {"bound": False}


def test_binding_present(client, monkeypatch):
    async def _row(_):
        return {"workspace": "/w", "session_id": "s1"}
    monkeypatch.setattr(db, "get_owui_binding", _row)
    r = client.get("/coder/binding?owui_chat_id=c1")
    assert r.json() == {"bound": True, "workspace": "/w", "session_id": "s1"}


def test_bind(client, monkeypatch):
    seen = {}
    async def _upsert(chat, ws, sid):
        seen.update(chat=chat, ws=ws, sid=sid)
    monkeypatch.setattr(db, "upsert_owui_binding", _upsert)
    r = client.post("/coder/bind", json={"owui_chat_id": "c1",
                                         "workspace": "/w", "session_id": "s1"})
    assert r.status_code == 200
    assert seen == {"chat": "c1", "ws": "/w", "sid": "s1"}


def test_request_approval_inserts_and_pushes(client, monkeypatch):
    captured = {}
    async def _insert(**kw):
        captured.update(kw)
        return 7
    pushed = {}
    monkeypatch.setattr(db, "insert_approval", _insert)
    monkeypatch.setattr(owui_runner, "push_approval",
                        lambda rid, ap: pushed.update(rid=rid, ap=ap) or True)
    r = client.post("/request_approval", json={
        "chat_id": 42, "prompt_text": "Run Bash?",
        "metadata": {"tool_name": "Bash"}})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "approval_id": 7}
    assert captured["chat_id"] == 42
    assert pushed["rid"] == 42
    assert pushed["ap"]["approval_id"] == 7
    assert pushed["ap"]["tool"] == "Bash"


def test_approve_updates_status(client, monkeypatch):
    seen = {}
    async def _update(aid, status, **kw):
        seen.update(aid=aid, status=status)
    monkeypatch.setattr(db, "update_approval_status", _update)
    r = client.post("/coder/approve", json={"approval_id": 9,
                                            "decision": "approved"})
    assert r.status_code == 204
    assert seen == {"aid": 9, "status": "approved"}


# --- /coder/stream ---

import asyncio  # noqa: E402

from telegram_gateway.coder import FeedItem  # noqa: E402


def _parse_sse(body: str):
    """Return [(event, data_str), ...] from an SSE response body."""
    frames = []
    for block in body.strip().split("\n\n"):
        ev, data = None, None
        for ln in block.splitlines():
            if ln.startswith("event: "):
                ev = ln[7:]
            elif ln.startswith("data: "):
                data = ln[6:]
        if ev:
            frames.append((ev, data))
    return frames


def test_stream_happy_path_and_approval(client, monkeypatch):
    RUN_ID = 777
    monkeypatch.setattr(owui_api, "_next_run_id", lambda: RUN_ID)

    async def _binding(_):
        return {"workspace": "/w", "session_id": "old-session"}
    upserts = []
    async def _upsert(chat, ws, sid):
        upserts.append((chat, ws, sid))
    monkeypatch.setattr(db, "get_owui_binding", _binding)
    monkeypatch.setattr(db, "upsert_owui_binding", _upsert)

    async def fake_turn(prompt, cwd, session_id=None, **kw):
        assert cwd == "/w"
        assert session_id == "old-session"
        yield FeedItem(kind="session", text="new-session"), None
        yield FeedItem(kind="text", text="working"), None
        # simulate the hook firing mid-turn for a gated tool
        owui_runner.push_approval(RUN_ID, {"approval_id": 5, "tool": "Bash",
                                           "summary": "Run Bash?"})
        await asyncio.sleep(0.05)  # let _merge surface the approval first
        yield FeedItem(kind="tool_use", text="Bash", detail="cmd: x"), None
        yield FeedItem(kind="_exit", text=""), 0

    monkeypatch.setattr(owui_runner, "run_coder_turn", fake_turn)

    r = client.post("/coder/stream", json={"owui_chat_id": "c1", "prompt": "go"})
    assert r.status_code == 200
    frames = _parse_sse(r.text)
    events = [e for e, _ in frames]
    assert events[0] == "session"
    assert "text" in events
    assert "approval" in events
    assert "tool_use" in events
    assert events[-1] == "done"
    # session id persisted, and the approval payload carried the id
    assert ("c1", "/w", "new-session") in upserts
    approval_frame = next(d for e, d in frames if e == "approval")
    assert '"approval_id": 5' in approval_frame
    # run unregistered after the stream finishes
    assert RUN_ID not in owui_runner.PENDING
