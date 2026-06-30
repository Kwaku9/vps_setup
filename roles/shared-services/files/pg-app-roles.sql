-- Least-privilege application roles for the shared `enterprise` database.
-- Replaces the practice of every consumer logging in as the `postgres` superuser.
--
-- Apply (as superuser), then set each role's password interactively:
--   cat pg-app-roles.sql | podman exec -i postgres psql -U postgres -d enterprise
--   podman exec -it postgres psql -U postgres -d enterprise
--     \password grafana_ro
--     \password session_ingest
--     \password ops_dashboard
--     \password telegram_gw
-- Then put the SAME passwords in vault.yml (pg_*_password vars). `postgres` stays
-- superuser for deploy-time DDL/migrations only — no running app uses it anymore.
--
-- Idempotent: safe to re-run.

-- 1. Privilege tiers (NOLOGIN group roles)
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_ro') THEN CREATE ROLE app_ro NOLOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_rw') THEN CREATE ROLE app_rw NOLOGIN; END IF;
END $$;

GRANT CONNECT ON DATABASE enterprise TO app_ro, app_rw;
GRANT USAGE ON SCHEMA public TO app_ro;
GRANT USAGE, CREATE ON SCHEMA public TO app_rw;   -- writers may create their own tables at runtime
-- Write-tier services run idempotent startup migrations that include
-- `CREATE SCHEMA IF NOT EXISTS ...` (e.g. telegram-gateway's `gateway` schema),
-- which requires database-level CREATE even when the schema already exists.
GRANT CREATE ON DATABASE enterprise TO app_rw;

-- Postgres 14+ predefined roles: cover all current AND future tables, any owner,
-- without per-table grant maintenance. Neither grants superuser or access to
-- pg_authid (role password hashes stay readable only by superuser).
GRANT pg_read_all_data  TO app_ro;
GRANT pg_read_all_data  TO app_rw;
GRANT pg_write_all_data TO app_rw;

-- 2. One LOGIN role per consumer (passwords set separately via \password)
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro')     THEN CREATE ROLE grafana_ro     LOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'session_ingest') THEN CREATE ROLE session_ingest LOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ops_dashboard')  THEN CREATE ROLE ops_dashboard  LOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'telegram_gw')    THEN CREATE ROLE telegram_gw    LOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'recall_ro')      THEN CREATE ROLE recall_ro      LOGIN; END IF;
END $$;

-- 3. Assign tiers
GRANT app_ro TO grafana_ro, recall_ro;                      -- read-only (Grafana dashboards; session-recall MCP)
GRANT app_rw TO session_ingest, ops_dashboard, telegram_gw; -- read-write consumers

-- Verify with:  \du   and   SELECT rolname FROM pg_roles WHERE rolname LIKE 'app\_%' OR rolname IN ('grafana_ro','session_ingest','ops_dashboard','telegram_gw','recall_ro');
