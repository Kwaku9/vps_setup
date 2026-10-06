-- 009: store Claude Code subagent transcripts in sessions.messages.
--
-- Subagent messages are stored redacted with is_sidechain = true and point at
-- their sessions.subagents row; each subagent records the parent Agent/Task
-- tool_use_id that spawned it and how that link was found. Every reader of the
-- main conversation filters NOT coalesce(is_sidechain, false) (commit adcbef3).
--
-- Run as the table OWNER (postgres): session_ingest cannot ALTER these tables.
-- ingest-sessions.py checks information_schema at startup and only attempts
-- this itself when a column is missing.
--
--   podman exec -i postgres psql -U postgres -d enterprise -v ON_ERROR_STOP=1 < 009_subagent_messages.sql
--
-- lock_timeout keeps an ALTER from queueing an exclusive lock in front of
-- production readers (2026-10-05 incident: a queued ALTER stalled every session
-- query). If it times out, nothing changed; rerun when the table is quiet.
SET lock_timeout = '3s';

ALTER TABLE sessions.subagents ADD COLUMN IF NOT EXISTS parent_tool_use_id text;
ALTER TABLE sessions.subagents ADD COLUMN IF NOT EXISTS link text;
ALTER TABLE sessions.messages ADD COLUMN IF NOT EXISTS subagent_id integer
    REFERENCES sessions.subagents(id) ON DELETE CASCADE;

-- Outside a transaction block (psql runs each statement on its own here).
CREATE INDEX CONCURRENTLY IF NOT EXISTS messages_subagent_id_idx
    ON sessions.messages (subagent_id) WHERE subagent_id IS NOT NULL;
