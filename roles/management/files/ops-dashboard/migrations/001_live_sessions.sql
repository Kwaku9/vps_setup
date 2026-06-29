-- 001_live_sessions.sql — idempotent. Safe to re-run.
-- Adds real-time live-state to sessions.sessions and an append-only event log.
\set ON_ERROR_STOP on
-- ^ fail loudly. A silently-failed CREATE UNIQUE INDEX (duplicate rows) is exactly
--   how the live-ingest ON CONFLICT bug hid for so long.

ALTER TABLE sessions.sessions ADD COLUMN IF NOT EXISTS live_status     text;
ALTER TABLE sessions.sessions ADD COLUMN IF NOT EXISTS needs_input     boolean NOT NULL DEFAULT false;
ALTER TABLE sessions.sessions ADD COLUMN IF NOT EXISTS current_stage   text;
ALTER TABLE sessions.sessions ADD COLUMN IF NOT EXISTS host            text;
ALTER TABLE sessions.sessions ADD COLUMN IF NOT EXISTS last_event_at   timestamptz;
ALTER TABLE sessions.sessions ADD COLUMN IF NOT EXISTS last_event_type text;

CREATE TABLE IF NOT EXISTS sessions.session_events (
    id          bigserial PRIMARY KEY,
    session_id  integer NOT NULL REFERENCES sessions.sessions(id) ON DELETE CASCADE,
    host        text,
    event_type  text NOT NULL,
    payload     jsonb,
    ts          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_session_events_session ON sessions.session_events(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_live_status   ON sessions.sessions(live_status)
    WHERE live_status IS NOT NULL AND live_status <> 'ended';
CREATE INDEX IF NOT EXISTS idx_sessions_last_event_at ON sessions.sessions(last_event_at);

-- Uniqueness the real-time upserts depend on (idempotency). A message uuid is
-- unique only WITHIN a session — resume/compaction replays a message (same uuid)
-- into other sessions — so the message constraint is (session_id, uuid), not (uuid).
CREATE UNIQUE INDEX IF NOT EXISTS uq_sessions_session_uuid ON sessions.sessions(session_uuid);
DROP   INDEX IF EXISTS sessions.uq_messages_uuid;
CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_session_uuid ON sessions.messages(session_id, uuid);
