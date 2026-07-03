#!/usr/bin/env python3
"""Re-embed OWUI knowledge-base chunks on the Fedora GPU, sync vectors to the VPS.

Companion to embed_recall_delta.py, but for OpenWebUI knowledge bases instead of
session recall. Reads openwebui.document_chunk (id, text) from the VPS postgres
(reached over the SSH tunnel that reindex-owui-kb-now.sh opens), embeds each chunk's
text with the LOCAL GPU EmbeddingGemma, and UPDATEs each row's vector in place. The
row's id / text / collection_name / vmetadata are never touched — only the vector.

Two correctness details that keep retrieval valid:
  * RAW text, no gemma task prompt. OWUI's `openai` RAG engine POSTs the plain chunk
    text to /embeddings, and it embeds the *query* the same way — so stored and query
    vectors must both be prompt-free to share one space. (This is why we do NOT use
    the `title: none | text:` wrapper that embed_recall_delta.py uses.)
  * Zero-pad 768 -> VECTOR_LENGTH (1536). OWUI's pgvector column is vector(1536) and
    OWUI pads every vector to that width via adjust_vector_length(); we match it, so
    the padded 768 embeddings sit in the same space as OWUI's padded query vectors
    (trailing zeros don't affect cosine).

Idempotent: --only-stale skips rows that already carry a 768-dim embeddinggemma vector
(any nonzero component beyond dim 384), so a re-run only fills what's missing.

Env: PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE, LITELLM_BASE, LITELLM_KEY (optional
     for a bare llama.cpp server), GEMMA_MODEL (default embeddinggemma),
     VECTOR_LENGTH (default 1536).
"""
import os
import sys
import time

import psycopg2
import requests

LITELLM_BASE = os.environ.get("LITELLM_BASE", "")
LITELLM_KEY = os.environ.get("LITELLM_KEY", "")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "embeddinggemma")
VECTOR_LENGTH = int(os.environ.get("VECTOR_LENGTH", "1536"))
ONLY_STALE = "--only-stale" in sys.argv
BATCH = 16


def pad(vec):
    # Match OWUI's adjust_vector_length: pad short vectors with zeros, truncate long.
    if len(vec) < VECTOR_LENGTH:
        return vec + [0.0] * (VECTOR_LENGTH - len(vec))
    return vec[:VECTOR_LENGTH]


def vec_literal(vec):
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def _post(inputs):
    headers = {"Authorization": f"Bearer {LITELLM_KEY}"} if LITELLM_KEY else {}
    r = requests.post(
        f"{LITELLM_BASE}/embeddings",
        headers=headers,
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
            print(f"embed_owui_kb: truncating overlong chunk ({len(s)} chars) and retrying", file=sys.stderr)
            return embed([s[: int(len(s) * 0.7)]])
        raise


SELECT_ALL = (
    "SELECT id, text FROM openwebui.document_chunk "
    "WHERE text IS NOT NULL AND length(trim(text)) > 0 ORDER BY id"
)
# --only-stale: a vector is 'stale' (old 384-dim MiniLM, or NULL) when it has NO
# nonzero component beyond position 384. A real embeddinggemma-768 vector does.
SELECT_STALE = (
    "SELECT id, text FROM openwebui.document_chunk "
    "WHERE text IS NOT NULL AND length(trim(text)) > 0 "
    "AND (vector IS NULL OR (SELECT count(*) FILTER (WHERE x <> 0) FROM "
    "unnest((string_to_array(trim(both '[]' from vector::text), ',')::float8[])[385:768]) x) = 0) "
    "ORDER BY id"
)


def main():
    if not LITELLM_BASE:
        raise SystemExit("embed_owui_kb: LITELLM_BASE env is required")

    conn = psycopg2.connect()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute(SELECT_STALE if ONLY_STALE else SELECT_ALL)
        rows = cur.fetchall()
        print(f"embed_owui_kb: {len(rows)} chunk(s) to embed ({'stale-only' if ONLY_STALE else 'all'})")
        n = 0
        t0 = time.time()
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i + BATCH]
            vecs = embed([r[1] for r in batch])
            for (cid, _text), v in zip(batch, vecs):
                cur.execute(
                    "UPDATE openwebui.document_chunk SET vector = %s::vector WHERE id = %s",
                    (vec_literal(pad(v)), cid),
                )
            conn.commit()
            n += len(batch)
            print(f"  {n}/{len(rows)}", flush=True)
        print(f"embed_owui_kb: updated {n} chunks in {time.time() - t0:.0f}s")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
