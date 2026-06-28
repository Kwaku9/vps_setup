-- summary_schema.sql — run as postgres: psql -U postgres -d enterprise -f summary_schema.sql
CREATE EXTENSION IF NOT EXISTS vector;

-- preserve the 83 harvested recaps as a benchmark before summary_text is overwritten by Haiku
ALTER TABLE spike.session_summary
  ADD COLUMN IF NOT EXISTS categories      text[],
  ADD COLUMN IF NOT EXISTS soft_entities   jsonb,
  ADD COLUMN IF NOT EXISTS harvested_recap text,
  ADD COLUMN IF NOT EXISTS model           text,
  ADD COLUMN IF NOT EXISTS generated_at    timestamptz;

UPDATE spike.session_summary
   SET harvested_recap = summary_text
 WHERE source = 'harvested_recap' AND harvested_recap IS NULL;

CREATE TABLE IF NOT EXISTS spike.session_summary_vec_nomic (
  session_uuid text PRIMARY KEY,
  embedding    vector(768),
  embedded_at  timestamptz DEFAULT now());

CREATE TABLE IF NOT EXISTS spike.session_summary_vec_gemma (
  session_uuid text PRIMARY KEY,
  embedding    vector(768),
  embedded_at  timestamptz DEFAULT now());

GRANT SELECT, INSERT, UPDATE ON spike.session_summary               TO session_ingest;
GRANT SELECT, INSERT, UPDATE ON spike.session_summary_vec_nomic     TO session_ingest;
GRANT SELECT, INSERT, UPDATE ON spike.session_summary_vec_gemma     TO session_ingest;
