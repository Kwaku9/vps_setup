CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS spike;

CREATE TABLE IF NOT EXISTS spike.emb_gemma_useronly (
  message_id bigint, chunk_idx int, session_uuid text, project text,
  ts timestamptz, snippet text, embedding vector(768),
  PRIMARY KEY (message_id, chunk_idx));
CREATE TABLE IF NOT EXISTS spike.emb_gemma_userasst (
  message_id bigint, chunk_idx int, session_uuid text, project text,
  ts timestamptz, snippet text, embedding vector(768),
  PRIMARY KEY (message_id, chunk_idx));

CREATE TABLE IF NOT EXISTS spike.emb_nomic_useronly (
  session_uuid text PRIMARY KEY, project text, started_at timestamptz,
  title text, embedding vector(768));
CREATE TABLE IF NOT EXISTS spike.emb_nomic_userasst (
  session_uuid text PRIMARY KEY, project text, started_at timestamptz,
  title text, embedding vector(768));

CREATE TABLE IF NOT EXISTS spike.kw_useronly (session_uuid text PRIMARY KEY, doc tsvector);
CREATE TABLE IF NOT EXISTS spike.kw_userasst (session_uuid text PRIMARY KEY, doc tsvector);
CREATE INDEX IF NOT EXISTS kw_useronly_gin ON spike.kw_useronly USING GIN (doc);
CREATE INDEX IF NOT EXISTS kw_userasst_gin ON spike.kw_userasst USING GIN (doc);

CREATE TABLE IF NOT EXISTS spike.eval_queries (
  id serial PRIMARY KEY, query text NOT NULL, gold_session_uuid text NOT NULL,
  source text, created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS spike.eval_relevance (
  id serial PRIMARY KEY, query_id int REFERENCES spike.eval_queries(id),
  method text, session_uuid text, is_relevant boolean, ts timestamptz DEFAULT now());

GRANT USAGE ON SCHEMA spike TO session_ingest;
GRANT ALL ON ALL TABLES IN SCHEMA spike TO session_ingest;
GRANT ALL ON ALL SEQUENCES IN SCHEMA spike TO session_ingest;
ALTER DEFAULT PRIVILEGES IN SCHEMA spike GRANT ALL ON TABLES TO session_ingest;
ALTER DEFAULT PRIVILEGES IN SCHEMA spike GRANT ALL ON SEQUENCES TO session_ingest;
