#!/usr/bin/env python3
"""Nightly freshness step for the session-recall store.

Embeds every user+assistant message NOT yet present in recall.chunks (gemma-512,
~2000-char chunks, EmbeddingGemma via LiteLLM) and inserts with ON CONFLICT DO
NOTHING. Idempotent and resumable: re-running is a no-op once everything is
embedded. Runs on the HOST (not in a pod), driven by daily-ingest.sh.

Env:
  PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE  (psycopg2 reads these)  -- session_ingest
  LITELLM_BASE   e.g. http://127.0.0.1:4000/v1
  LITELLM_KEY    LiteLLM master key
  GEMMA_MODEL    default 'embeddinggemma'
"""
import os
import sys
import time
from pathlib import Path

import psycopg2
import requests

# Redact BEFORE embedding. The corpus is read by the recall MCP and is a
# candidate for public search, so it must be clean AT REST — an export-time
# filter only protects the export you remembered to filter.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "redaction"))
from redact import load_from_env  # noqa: E402

_REDACTOR = load_from_env()

LITELLM_BASE = os.environ.get("LITELLM_BASE", "")
LITELLM_KEY = os.environ.get("LITELLM_KEY", "")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "embeddinggemma")
CHUNK_CHARS = 2000
BATCH = 32


def gemma_doc(text):
    return f"title: none | text: {text}"


def vec_literal(vec):
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def chunk_text(text, n=CHUNK_CHARS):
    text = (text or "").strip()
    if not text:
        return []
    return [text[i:i + n] for i in range(0, len(text), n)]


def _post(inputs):
    r = requests.post(
        f"{LITELLM_BASE}/embeddings",
        headers={"Authorization": f"Bearer {LITELLM_KEY}"},
        json={"model": GEMMA_MODEL, "input": inputs},
        timeout=300,
    )
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def embed(inputs):
    # EmbeddingGemma (llama.cpp) 500s when an input exceeds its 2048-tok context.
    # Split the batch to isolate the offender; truncate a lone overlong item.
    try:
        return _post(inputs)
    except requests.HTTPError:
        if len(inputs) > 1:
            mid = len(inputs) // 2
            return embed(inputs[:mid]) + embed(inputs[mid:])
        s = inputs[0]
        if len(s) > 800:
            print(f"embed_recall_delta: truncating overlong item ({len(s)} chars) and retrying", file=sys.stderr)
            return embed([s[: int(len(s) * 0.7)]])
        raise


# Filter on a non-whitespace char (~ '[^[:space:]]'), NOT length(trim())>0:
# PG trim() strips only spaces, so whitespace-only bodies (e.g. two newlines)
# pass it, but Python .strip() empties them -> chunk_text() yields nothing ->
# they never persist and get re-selected every run (a never-converging delta).
# (Keep this note in Python, not inside the SQL string: a backslash-n in a
# triple-quoted string becomes a real newline and would break an SQL comment.)
SELECT_NEW = """
    SELECT m.id, s.session_uuid,
           COALESCE(p.display_name, p.project_path) AS project,
           m.timestamp, m.content_text
    FROM sessions.messages m
    JOIN sessions.sessions s ON s.id = m.session_id
    JOIN sessions.projects p ON p.id = s.project_id
    WHERE m.type IN ('user','assistant')
      AND m.content_text IS NOT NULL
      AND m.content_text ~ '[^[:space:]]'
      AND NOT EXISTS (SELECT 1 FROM recall.chunks rc WHERE rc.message_id = m.id)
    ORDER BY m.id
"""

INSERT = (
    "INSERT INTO recall.chunks "
    "(message_id, chunk_idx, session_uuid, project, ts, snippet, embedding) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s::vector) ON CONFLICT DO NOTHING"
)


def main():
    if not LITELLM_BASE:
        raise SystemExit("embed_recall_delta: LITELLM_BASE env is required")

    # A server-side (named) read cursor needs an open transaction and is
    # invalidated by COMMIT, so reads and writes use SEPARATE connections
    # (see embed_sessions.py spike NOTE). rconn stays autocommit=False (one
    # long read transaction, never committed); wconn does the inserts+commits.
    rconn = psycopg2.connect()
    rconn.autocommit = False
    wconn = psycopg2.connect()
    wconn.autocommit = False
    try:
        rcur = rconn.cursor(name="recall_delta")
        rcur.itersize = 1000
        rcur.execute(SELECT_NEW)
        wcur = wconn.cursor()

        pending = []  # (message_id, chunk_idx, session_uuid, project, ts, snippet, raw_chunk)
        n = 0
        t0 = time.time()

        def flush():
            nonlocal pending
            if not pending:
                return
            vecs = embed([gemma_doc(p[6]) for p in pending])
            for p, v in zip(pending, vecs):
                wcur.execute(INSERT, (p[0], p[1], p[2], p[3], p[4], p[5], vec_literal(v)))
            wconn.commit()
            pending = []

        for mid, uuid, project, ts, content in rcur:
            # Redact the WHOLE message before chunking. Redacting each chunk
            # instead would miss any secret straddling a 2000-char boundary,
            # since neither half matches the pattern on its own.
            content = _REDACTOR.text(content)
            for ci, ch in enumerate(chunk_text(content)):
                pending.append((mid, ci, uuid, project, ts, ch[:500], ch))
                if len(pending) >= BATCH:
                    flush()
            n += 1
        flush()
        print(f"recall-delta: embedded deltas for {n} new messages in {time.time()-t0:.0f}s")
        return 0
    finally:
        rconn.close()
        wconn.close()


if __name__ == "__main__":
    sys.exit(main())
