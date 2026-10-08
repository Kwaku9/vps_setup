-- Idempotent: run as the migration owner, not the dashboard's application role.
\set ON_ERROR_STOP on
CREATE TABLE IF NOT EXISTS sessions.workstation_sessions (
    session_id integer PRIMARY KEY REFERENCES sessions.sessions(id) ON DELETE CASCADE,
    host text NOT NULL,
    name text,
    agent_kind text NOT NULL CHECK (agent_kind IN ('claude', 'codex')),
    input_available boolean NOT NULL DEFAULT false,
    last_seen timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions.input_requests (
    id uuid PRIMARY KEY,
    session_id integer NOT NULL REFERENCES sessions.sessions(id) ON DELETE CASCADE,
    host text NOT NULL,
    text text NOT NULL,
    created_by text NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'claimed', 'delivered', 'failed', 'uncertain')),
    detail text,
    created_at timestamptz NOT NULL DEFAULT now(),
    claimed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS input_requests_pending ON sessions.input_requests(host, created_at)
    WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS input_requests_session ON sessions.input_requests(session_id, created_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON sessions.workstation_sessions, sessions.input_requests TO ops_dashboard;
