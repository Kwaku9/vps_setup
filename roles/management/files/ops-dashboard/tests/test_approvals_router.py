import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ops_dashboard.api.routers import approvals


class FakeConn:
    def __init__(self, execute_result="UPDATE 1"):
        self.execute_result = execute_result
        self.queries = []

    async def execute(self, q, *args):
        self.queries.append((q, args))
        return self.execute_result


@pytest.mark.asyncio
async def test_apply_decision_true_on_one_row():
    conn = FakeConn("UPDATE 1")
    ok = await approvals.apply_decision(conn, 7, "approve")
    assert ok is True
    assert conn.queries[0][1] == (7, "approved")


@pytest.mark.asyncio
async def test_apply_decision_false_when_no_row():
    conn = FakeConn("UPDATE 0")
    ok = await approvals.apply_decision(conn, 7, "deny")
    assert ok is False
    assert conn.queries[0][1] == (7, "denied")


def test_decide_rejects_bad_decision():
    app = FastAPI()
    app.state.db_pool = None
    app.include_router(approvals.router)
    c = TestClient(app)
    r = c.post("/api/approvals/5/decide", json={"decision": "maybe"})
    assert r.status_code == 422


def test_pending_empty_without_pool():
    app = FastAPI()
    app.state.db_pool = None
    app.include_router(approvals.router)
    c = TestClient(app)
    r = c.get("/api/approvals/pending")
    assert r.status_code == 200
    assert r.json() == []
