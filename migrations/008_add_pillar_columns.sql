-- 008_add_pillar_columns.sql — LLM-assigned platform pillar per session.
--
-- The Journey Tracker used to classify sessions into pillars by keyword-matching
-- the raw first prompt only, which left 53% of sessions in "General Platform
-- Work". classify-sessions.py (step 3b of run-daily-timeline.sh) now also assigns
-- a pillar from the authored summary + project + touched files, and
-- extract-sessions.js combines that with deterministic project/path/keyword
-- signals. Taxonomy: journey-tracker/pillars.json (shipped next to the classifier).
--
-- Idempotent, additive, safe to re-run. Apply as postgres:
--   podman cp migrations/008_add_pillar_columns.sql postgres:/tmp/008.sql
--   podman exec postgres psql -U postgres -d enterprise -v ON_ERROR_STOP=1 -f /tmp/008.sql
BEGIN;

ALTER TABLE sessions.sessions
  ADD COLUMN IF NOT EXISTS pillar_id         text,
  ADD COLUMN IF NOT EXISTS pillar_confidence real,
  ADD COLUMN IF NOT EXISTS pillar_model      text,
  ADD COLUMN IF NOT EXISTS pillar_version    integer;

CREATE INDEX IF NOT EXISTS idx_sessions_pillar ON sessions.sessions (pillar_id);

-- session_ingest already owns the table; recall_ro reads via app_ro. Nothing to grant.

COMMIT;
