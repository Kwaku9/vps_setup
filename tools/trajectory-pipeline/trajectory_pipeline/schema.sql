-- Additive: existing sessions.*, recall.*, and graph loaders are untouched.
CREATE SCHEMA IF NOT EXISTS learning;
CREATE TABLE IF NOT EXISTS learning.traces (
  id text PRIMARY KEY, session_uuid text NOT NULL, snapshot_hash text NOT NULL,
  payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS learning.decisions (
  id text PRIMARY KEY, trace_id text NOT NULL REFERENCES learning.traces(id),
  status text NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS learning.graph_outbox (
  id bigserial PRIMARY KEY, event_key text UNIQUE NOT NULL, payload jsonb NOT NULL,
  delivered_at timestamptz, attempts integer NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS learning.lessons (
  id text PRIMARY KEY, lesson_key text NOT NULL,
  trace_id text NOT NULL REFERENCES learning.traces(id),
  statement text NOT NULL, scope text NOT NULL,
  observed_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
  supersedes text REFERENCES learning.lessons(id),
  CHECK (expires_at > observed_at)
);
CREATE TABLE IF NOT EXISTS learning.model_jobs (
  id text PRIMARY KEY, payload jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION learning.reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable learning evidence'; END; $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='learning_traces_immutable') THEN
    CREATE TRIGGER learning_traces_immutable BEFORE UPDATE OR DELETE ON learning.traces
      FOR EACH ROW EXECUTE FUNCTION learning.reject_mutation();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='learning_decisions_immutable') THEN
    CREATE TRIGGER learning_decisions_immutable BEFORE UPDATE OR DELETE ON learning.decisions
      FOR EACH ROW EXECUTE FUNCTION learning.reject_mutation();
  END IF;
END $$;
-- Provision a dedicated learning_ingest login separately; do not use postgres.
-- GRANT USAGE ON SCHEMA learning TO learning_ingest;
-- GRANT SELECT, INSERT ON learning.traces, learning.decisions, learning.lessons TO learning_ingest;
-- GRANT SELECT, INSERT, UPDATE ON learning.graph_outbox, learning.model_jobs TO learning_ingest;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA learning TO learning_ingest;
