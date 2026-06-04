-- OWUI persistence bootstrap: isolated schema + pgvector, inside the shared `enterprise` DB.
-- Idempotent; safe to re-run on every deploy.
-- OWUI connects as `postgres` with search_path=openwebui,public and is confined to the
-- `openwebui` schema; the `vector` type lives in `public` (on the search_path).
CREATE SCHEMA IF NOT EXISTS openwebui AUTHORIZATION postgres;
CREATE EXTENSION IF NOT EXISTS vector;
COMMENT ON SCHEMA openwebui IS 'Open WebUI relational + pgvector store (migrated from SQLite/Chroma 2026-06-04)';
