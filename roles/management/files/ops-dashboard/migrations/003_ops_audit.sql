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

-- The REVOKE alone is not enough: ops_dashboard is a member of app_rw, whose
-- inherited write-everything rights cannot be revoked per table. A trigger
-- applies whatever the caller's grants, so only a superuser (who can disable
-- it, deliberately) may change or remove history.
CREATE OR REPLACE FUNCTION sessions.ops_audit_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        RAISE EXCEPTION 'sessions.ops_audit is append-only (% refused for %)', TG_OP, current_user;
    END IF;
    -- Superuser: let the change through. A row trigger returning NULL would
    -- silently skip the row instead.
    IF TG_LEVEL = 'ROW' THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS ops_audit_no_change ON sessions.ops_audit;
CREATE TRIGGER ops_audit_no_change BEFORE UPDATE OR DELETE ON sessions.ops_audit
    FOR EACH ROW EXECUTE FUNCTION sessions.ops_audit_append_only();
DROP TRIGGER IF EXISTS ops_audit_no_truncate ON sessions.ops_audit;
CREATE TRIGGER ops_audit_no_truncate BEFORE TRUNCATE ON sessions.ops_audit
    FOR EACH STATEMENT EXECUTE FUNCTION sessions.ops_audit_append_only();
