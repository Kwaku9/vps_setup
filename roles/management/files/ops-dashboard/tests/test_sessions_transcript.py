import json
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ops_dashboard.api.routers.sessions import router


@pytest.mark.parametrize("encoded", [True, False])
@pytest.mark.parametrize("cursor_name,column", [("since", "m.sequence_num"), ("after_id", "m.id")])
def test_transcript_preserves_structured_cli_blocks_and_cursor(encoded, cursor_name, column):
    blocks = [{"type": "tool_use", "id": "call-1", "name": "Bash", "input": {"command": "pwd"}}]
    text = "Full response " * 300
    captured = {}

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield self

        async def fetch(self, query, *args):
            captured.update(query=query, args=args)
            return [
                {"cursor": 101, "uuid": "call", "role": "assistant", "type": "assistant", "content_text": None,
                 "content_json": json.dumps(blocks) if encoded else blocks, "sequence_num": 11, "timestamp": None},
                {"cursor": 102, "uuid": "prose", "role": "assistant", "type": "assistant", "content_text": text,
                 "content_json": None, "sequence_num": 12, "timestamp": None},
            ]

    app = FastAPI()
    app.state.db_pool = Pool()
    app.include_router(router)
    response = TestClient(app).get(f"/api/sessions/session-1/transcript?{cursor_name}=10")
    assert response.status_code == 200
    assert response.json()[0]["content_json"] == blocks
    assert response.json()[1]["content_text"] == text
    assert captured["args"] == ("session-1", 10)
    assert response.json()[1]["cursor"] == 102
    assert f"{column} > $2" in captured["query"]
    assert f"ORDER BY {column} ASC" in captured["query"]
    assert "NOT coalesce(m.is_sidechain, false)" in captured["query"]


def test_transcript_without_database_is_empty():
    app = FastAPI()
    app.state.db_pool = None
    app.include_router(router)
    assert TestClient(app).get("/api/sessions/session-1/transcript").json() == []
