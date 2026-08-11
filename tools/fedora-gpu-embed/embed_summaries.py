#!/usr/bin/env python3
"""Embed session SUMMARIES into recall.summaries on the laptop GPU.

Sibling of embed_recall_delta.py and deliberately identical in shape: same
EmbeddingGemma model, same `title: none | text: ...` document prefix, same pgvector
literal, same batch size. Both write 768-dim vectors, so chunks and summaries live in
one comparable space.

The difference is WHAT is indexed. recall.chunks indexes PROCESS — 69k+ message
chunks. This indexes CONCLUSIONS — one row per session, the authored summary. That is
the layer that makes "what did you do about X?" answerable instead of only
"what's recent?".

Runs on the LAPTOP (the GPU is here); writes to the VPS Postgres over the SSH tunnel
opened by the wrapper. Env matches embed-recall-now.sh:
    PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD, LITELLM_BASE, LITELLM_KEY, GEMMA_MODEL
"""
import os
import sys

import psycopg2
import requests

LITELLM_BASE = os.environ.get("LITELLM_BASE", "")
LITELLM_KEY = os.environ.get("LITELLM_KEY", "")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "embeddinggemma")
BATCH = 32


def gemma_doc(text):
    # Same prefix convention as embed_recall_delta.py — the vectors must live in the
    # same space as recall.chunks or cross-comparison is meaningless.
    return f"title: none | text: {text}"


def vec_literal(vec):
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


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
    """EmbeddingGemma (llama.cpp) 500s when an input exceeds its 2048-tok context.
    Split to isolate the offender; truncate a lone overlong item."""
    try:
        return _post(inputs)
    except Exception:
        if len(inputs) == 1:
            return _post([inputs[0][:4000]])
        mid = len(inputs) // 2
        return embed(inputs[:mid]) + embed(inputs[mid:])


SELECT_NEW = """
    SELECT ss.session_uuid,
           coalesce(pr.display_name, '') AS project,
           se.started_at,
           ss.visibility,
           trim(ss.one_liner || ' ' || coalesce(ss.paragraph, '')) AS snippet
      FROM sessions.session_summaries ss
      JOIN sessions.sessions se ON se.session_uuid = ss.session_uuid
      LEFT JOIN sessions.projects pr ON pr.id = se.project_id
     WHERE NOT EXISTS (
             SELECT 1 FROM recall.summaries rs WHERE rs.session_uuid = ss.session_uuid)
"""

INSERT = (
    "INSERT INTO recall.summaries "
    "(session_uuid, project, ts, visibility, snippet, embedding, model) "
    "VALUES (%s,%s,%s,%s,%s,%s::vector,%s) "
    "ON CONFLICT (session_uuid) DO UPDATE SET "
    "  project=EXCLUDED.project, ts=EXCLUDED.ts, visibility=EXCLUDED.visibility, "
    "  snippet=EXCLUDED.snippet, embedding=EXCLUDED.embedding, "
    "  model=EXCLUDED.model, embedded_at=now()"
)


def main():
    conn = psycopg2.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "enterprise"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ["PGPASSWORD"],
    )
    cur = conn.cursor()
    cur.execute(SELECT_NEW)
    rows = cur.fetchall()
    print(f"summaries to embed: {len(rows)}  model={GEMMA_MODEL}", flush=True)
    if not rows:
        conn.close()
        return

    written = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        vecs = embed([gemma_doc(r[4]) for r in batch])
        for (uuid, project, ts, vis, snippet), vec in zip(batch, vecs):
            cur.execute(INSERT, (uuid, project, ts, vis, snippet,
                                 vec_literal(vec), GEMMA_MODEL))
        conn.commit()          # commit per batch so an interrupted run keeps progress
        written += len(batch)
        print(f"  ...{written}/{len(rows)}", flush=True)

    conn.close()
    print(f"embedded={written}")


if __name__ == "__main__":
    sys.exit(main())
