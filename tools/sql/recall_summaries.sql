-- Embedded session SUMMARIES — the "conclusions" layer of the recall index.
--
-- Why a separate table rather than recall.chunks: chunks is PK (message_id,
-- chunk_idx) with a FOREIGN KEY to sessions.messages, so every row must belong to a
-- real message. A summary belongs to a SESSION, not a message, and has no message_id
-- to hang off. Same 768-dim EmbeddingGemma space, so the two are directly comparable
-- and a query can search either or both.
--
-- The point of this table: recall.chunks indexes PROCESS (what was said, 69k+ chunks);
-- this indexes CONCLUSIONS (what was achieved, one row per session). Retrieval over
-- conclusions measured 41.2 -> 67.2 R@10 at 32x lower latency in the semantic-search
-- work, which is the whole reason for building it.
--
-- visibility mirrors sessions.session_summaries so a PUBLIC consumer (the buildfol.io
-- widget) can filter on it without a second join. Default 'private'.

CREATE TABLE IF NOT EXISTS recall.summaries (
    session_uuid text PRIMARY KEY,
    project      text,
    ts           timestamptz,
    visibility   text NOT NULL DEFAULT 'private',
    snippet      text NOT NULL,        -- one_liner + paragraph, what was embedded
    embedding    vector(768) NOT NULL,
    model        text,
    embedded_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT recall_summaries_visibility_ck CHECK (visibility IN ('private','public'))
);

CREATE INDEX IF NOT EXISTS recall_summaries_visibility_idx
    ON recall.summaries (visibility);

-- Cosine similarity, matching how recall.chunks is queried.
CREATE INDEX IF NOT EXISTS recall_summaries_embedding_idx
    ON recall.summaries USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- The laptop embedder connects as session_ingest (same role embed_recall_delta.py
-- uses for recall.chunks), so it needs read on the source tables and write here.
GRANT USAGE ON SCHEMA recall TO session_ingest;
GRANT SELECT, INSERT, UPDATE ON recall.summaries TO session_ingest;
GRANT SELECT ON sessions.session_summaries, sessions.sessions, sessions.projects TO session_ingest;

-- NOTE: build the ivfflat index AFTER the table is populated. Creating it on an empty
-- table gives "little data ... low recall"; rebuild with lists ~= sqrt(rows):
--   DROP INDEX recall.recall_summaries_embedding_idx;
--   CREATE INDEX recall_summaries_embedding_idx ON recall.summaries
--       USING ivfflat (embedding vector_cosine_ops) WITH (lists = 44);
--   ANALYZE recall.summaries;
