-- 004_access_requests.sql — idempotent. Safe to re-run.
-- The request desk: any signed-in account asks for more access at
-- portal.<domain>/request; an admin approves or denies it in the ops dashboard.
-- Every decision is also written to sessions.ops_audit, so this table holds the
-- queue and its current state, and the audit table holds the history.
\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS sessions.access_requests (
    id           bigserial PRIMARY KEY,
    created_at   timestamptz NOT NULL DEFAULT now(),
    email        text NOT NULL,          -- from the verified Cloudflare Access token, lower case
    username     text,                   -- Authentik username at request time, when found
    kind         text NOT NULL,          -- students | paid_users | other
    reason       text NOT NULL,
    status       text NOT NULL DEFAULT 'pending',  -- pending | approved | denied | withdrawn
    decided_at   timestamptz,
    decided_by   text,
    note         text,                   -- the admin's reply, shown to the requester
    CONSTRAINT access_requests_kind_ck   CHECK (kind IN ('students', 'paid_users', 'other')),
    CONSTRAINT access_requests_status_ck CHECK (status IN ('pending', 'approved', 'denied', 'withdrawn'))
);

-- One open request per person per kind.
CREATE UNIQUE INDEX IF NOT EXISTS access_requests_one_open
    ON sessions.access_requests (email, kind) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS access_requests_email_idx  ON sessions.access_requests (email, created_at DESC);
CREATE INDEX IF NOT EXISTS access_requests_status_idx ON sessions.access_requests (status, created_at DESC);

GRANT SELECT, INSERT, UPDATE ON sessions.access_requests TO ops_dashboard;
GRANT USAGE ON SEQUENCE sessions.access_requests_id_seq TO ops_dashboard;
REVOKE DELETE, TRUNCATE ON sessions.access_requests FROM ops_dashboard;
