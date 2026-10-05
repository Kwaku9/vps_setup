-- 003_ops_audit.sql — idempotent. Safe to re-run.
-- Who did what on the ops dashboard: logins, page loads, denied requests and
-- every state-changing action, with the exact host command where one ran.
-- Append-only for the app: ops_dashboard may INSERT and SELECT, never UPDATE or
-- DELETE, so a compromised dashboard cannot rewrite its own history.
\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS sessions.ops_audit (
    id          bigserial PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    username    text NOT NULL,          -- OIDC preferred_username, CF Access email, or 'anonymous'
    role        text,                   -- viewer | operator | admin | NULL when unauthenticated
    action      text NOT NULL,          -- login | logout | page | ws-connect | start | stop | profile-switch | ...
    target      text,                   -- service / profile / approval id / path
    via         text,                   -- admission path: cf | breakglass | tailnet | direct
    outcome     text NOT NULL,          -- ok | failed | forbidden | unauthenticated | error
    method      text,
    route       text,
    status      integer,
    client_ip   text,
    user_agent  text,
    detail      jsonb
);

CREATE INDEX IF NOT EXISTS ops_audit_ts_idx   ON sessions.ops_audit (ts DESC);
CREATE INDEX IF NOT EXISTS ops_audit_user_idx ON sessions.ops_audit (username, ts DESC);

GRANT SELECT, INSERT ON sessions.ops_audit TO ops_dashboard;
GRANT USAGE ON SEQUENCE sessions.ops_audit_id_seq TO ops_dashboard;
REVOKE UPDATE, DELETE, TRUNCATE ON sessions.ops_audit FROM ops_dashboard;
