-- recall_schema.sql — production session-embedding store.
-- Run as postgres: podman exec -i postgres psql -U postgres -d enterprise -f /tmp/recall_schema.sql
-- Idempotent: safe to re-run.
CREATE SCHEMA IF NOT EXISTS recall;
CREATE EXTENSION IF NOT EXISTS vector;

-- gemma-512 chunks over user+assistant messages (the bake-off-winning dataset).
CREATE TABLE IF NOT EXISTS recall.chunks (
  message_id   bigint,
  chunk_idx    int,
  session_uuid text,
  project      text,
  ts           timestamptz,
  snippet      text,
  embedding    vector(768),
  PRIMARY KEY (message_id, chunk_idx)
);

-- ANN index for fast cosine search.
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
  ON recall.chunks USING hnsw (embedding vector_cosine_ops);
-- Pre-filter support for the optional project / since arguments.
CREATE INDEX IF NOT EXISTS chunks_project_idx ON recall.chunks (project);
CREATE INDEX IF NOT EXISTS chunks_ts_idx      ON recall.chunks (ts);

-- Read path (MCP server) — recall_ro already holds pg_read_all_data via app_ro;
-- these explicit grants are belt-and-suspenders and make intent legible.
GRANT USAGE ON SCHEMA recall TO recall_ro;
GRANT SELECT ON recall.chunks TO recall_ro;

-- Write path (nightly freshness step) — session_ingest is app_rw.
GRANT USAGE ON SCHEMA recall TO session_ingest;
GRANT SELECT, INSERT ON recall.chunks TO session_ingest;
