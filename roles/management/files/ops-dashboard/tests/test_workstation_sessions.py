"""API boundaries plus optional isolated PostgreSQL integration.

OPS_TEST_DSN is accepted only for the dedicated localhost test port; never point
these schema-building tests at the production sessions database.
"""
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from ops_dashboard.api.routers import workstations

SID = "12ebe03e-3ea9-4c97-9efc-9bfbad839f7d"
OTHER = "4e1edf95-ea57-47d7-9ead-fc444f3652a2"
KEY = "test-ingest-key-only-not-a-production-secret"


def token(host):
    return hmac.new(KEY.encode(), ("ops-workstation:v1:" + host).encode(), hashlib.sha256).hexdigest()


def test_machine_tokens_are_scoped_and_not_the_ingest_key(monkeypatch):
    monkeypatch.setenv("SESSION_INGEST_TOKEN", KEY)
    monkeypatch.setenv("OPS_WORKSTATION_HOSTS", "fedora,other")
    assert workstations.bridge_host("Bearer " + token("fedora")) == "fedora"
    assert workstations.bridge_host("Bearer " + token("other")) == "other"
    for invalid in [None, "Bearer " + KEY, "Bearer " + token("unlisted"), token("fedora")]:
        with pytest.raises(HTTPException) as exc:
            workstations.bridge_host(invalid)
        assert exc.value.status_code == 401


def test_reply_role_and_payload_validation_without_database():
    app = FastAPI()
    app.state.db_pool = None
    app.include_router(workstations.router)

    @app.middleware("http")
    async def viewer(request: Request, call_next):
        request.state.user = {"role": request.headers.get("test-role", "viewer"), "username": "test"}
        return await call_next(request)

    with TestClient(app) as client:
        url = f"/api/sessions/{SID}/input"
        assert client.post(url, json={"id": str(uuid4()), "text": "Hello"}).status_code == 403
        for text in ["", "  ", "\x00", "x" * 16001]:
            assert client.post(url, headers={"test-role": "operator"}, json={"id": str(uuid4()), "text": text}).status_code == 422
        assert client.post(url, headers={"test-role": "operator"}, json={"id": str(uuid4()), "text": "Hello"}).status_code == 503


BASE_SCHEMA = """
DROP SCHEMA IF EXISTS sessions CASCADE;
CREATE SCHEMA sessions;
DO $$ BEGIN CREATE ROLE ops_dashboard; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE TABLE sessions.projects(id serial PRIMARY KEY,project_path text UNIQUE,display_name text,source text);
CREATE TABLE sessions.sessions(id serial PRIMARY KEY,session_uuid text UNIQUE,project_id int,source text,
 git_branch text,host text,live_status text,needs_input boolean,current_stage text,last_event_at timestamptz,
 last_event_type text,status text,started_at timestamptz,ended_at timestamptz,model text);
CREATE TABLE sessions.messages(id serial PRIMARY KEY,session_id int,uuid text,parent_uuid text,type text,
 role text,content_text text,content_json jsonb,model text,input_tokens int,output_tokens int,cache_read_tokens int,
 cache_creation_tokens int,is_sidechain boolean,cwd text,timestamp timestamptz,sequence_num int,UNIQUE(session_id,uuid));
CREATE TABLE sessions.tool_calls(message_id int,session_id int,tool_use_id text,tool_name text,input_json jsonb,
 result_text text,status text,timestamp timestamptz,sequence_num int);
CREATE TABLE sessions.session_events(session_id int,host text,event_type text,payload jsonb,ts timestamptz);
"""


@pytest.fixture
def db_client(monkeypatch):
    dsn = os.environ.get("OPS_TEST_DSN")
    if not dsn:
        pytest.skip("set OPS_TEST_DSN to the disposable local test database")
    address = urlparse(dsn)
    assert address.hostname in ("localhost", "127.0.0.1") and address.port == 55439
    monkeypatch.setenv("SESSION_INGEST_TOKEN", KEY)
    monkeypatch.setenv("OPS_WORKSTATION_HOSTS", "fedora,other")

    async def audit(*args, **kwargs):
        pass

    monkeypatch.setattr(workstations.audit, "record", audit)

    @asynccontextmanager
    async def lifespan(app):
        app.state.db_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(BASE_SCHEMA)
            migration = Path(__file__).parents[1] / "migrations/004_workstation_sessions.sql"
            await conn.execute(migration.read_text().replace("\\set ON_ERROR_STOP on", ""))
        yield
        await app.state.db_pool.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(workstations.router)

    @app.middleware("http")
    async def operator(request: Request, call_next):
        request.state.user = {"role": "operator", "username": "test"}
        return await call_next(request)

    with TestClient(app) as client:
        yield client


def sync(client, host="fedora", sid=SID, connected=True, lines=None):
    return client.post("/api/workstations/sync", headers={"Authorization": "Bearer " + token(host)},
                       json={"sessions": [{"session_uuid": sid, "agent_kind": "claude", "name": "Test session",
                             "cwd": "/test", "state": "idle", "input_available": connected,
                             "transcript_delta": lines or []}]})


def test_real_ingest_queue_claim_host_isolation_and_duplicate_receipts(db_client):
    c = db_client
    assert sync(c).status_code == 200
    assert sync(c, host="other").status_code == 409  # cannot hijack another machine's session
    rid = str(uuid4())
    url = f"/api/sessions/{SID}/input"
    payload = {"id": rid, "text": "Test reply"}
    assert c.post(url, json=payload).status_code == 202
    assert c.post(url, json=payload).status_code == 202
    assert c.post(url, json={**payload, "text": "Changed"}).status_code == 409
    assert sync(c, host="other", sid=OTHER).json()["commands"] == []
    response = sync(c).json()
    assert len(response["commands"]) == 1
    assert response["commands"][0]["text"] == "Test reply"
    assert sync(c).json()["commands"] == []  # a claimed command is never silently repeated
    receipt = {"id": rid, "status": "delivered", "detail": "Queued in native test client"}
    assert c.post("/api/workstations/result", headers={"Authorization": "Bearer " + token("other")}, json=receipt).status_code == 404
    assert c.post("/api/workstations/result", headers={"Authorization": "Bearer " + token("fedora")}, json=receipt).status_code == 200
    assert c.post("/api/workstations/result", headers={"Authorization": "Bearer " + token("fedora")}, json=receipt).status_code == 200
    rows = c.get(url).json()
    assert len(rows) == 1 and rows[0]["status"] == "delivered"


def test_disconnected_session_rejects_input_and_mismatched_transcript(db_client):
    c = db_client
    assert sync(c, connected=False).status_code == 200
    assert c.post(f"/api/sessions/{SID}/input", json={"id": str(uuid4()), "text": "No"}).status_code == 409
    wrong = json.dumps({"sessionId": OTHER, "type": "user", "uuid": "wrong", "message": {"content": "wrong"}})
    assert sync(c, lines=[wrong]).status_code == 422


def test_live_session_history_upload_and_bounded_pending_input(db_client):
    c = db_client
    line = json.dumps({"sessionId": SID, "type": "assistant", "uuid": "message", "timestamp": "2026-10-08T10:00:00Z",
                       "message": {"role": "assistant", "content": [{"type": "text", "text": "Long text " * 1000}]}})
    assert sync(c, lines=[line]).status_code == 200
    assert sync(c, lines=[line]).status_code == 200
    for _ in range(4):
        assert c.post(f"/api/sessions/{SID}/input", json={"id": str(uuid4()), "text": "Next"}).status_code == 202
    assert c.post(f"/api/sessions/{SID}/input", json={"id": str(uuid4()), "text": "Too many"}).status_code == 429
