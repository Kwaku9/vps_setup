-- Read-only login for the trajectory pipeline (enterprise DB, `postgres` container).
-- Applied 2026-10-05. Rebuild with:
--   podman exec -i postgres psql -U postgres -d enterprise -v ON_ERROR_STOP=1 < learning_reader.sql
-- after replacing :'verifier' with a SCRAM-SHA-256 verifier (never a plaintext
-- password, so no log or history ever holds it), e.g. psql -v verifier='SCRAM-SHA-256$4096:...'.
-- Verified: SELECT on sessions.* works; INSERT/UPDATE/CREATE are denied by privilege
-- even with default_transaction_read_only turned off; openwebui.* and recall.* denied;
-- a wrong password is rejected.
BEGIN;
CREATE ROLE learning_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  CONNECTION LIMIT 4 PASSWORD :'verifier';
ALTER ROLE learning_reader SET default_transaction_read_only = on;
ALTER ROLE learning_reader SET statement_timeout = '10min';
-- Added 2026-10-05: a pull holding one transaction blocked a migration's ALTER
-- TABLE, and every session query queued behind it. Never hold locks idle.
ALTER ROLE learning_reader SET idle_in_transaction_session_timeout = '60s';
GRANT CONNECT ON DATABASE enterprise TO learning_reader;
GRANT USAGE ON SCHEMA sessions TO learning_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA sessions TO learning_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA sessions GRANT SELECT ON TABLES TO learning_reader;
COMMIT;
