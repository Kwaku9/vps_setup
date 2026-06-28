-- gemma-512 chunk-size variant tables (RAG-finer ~512-token / ~2000-char chunks)
CREATE TABLE IF NOT EXISTS spike.emb_gemma512_useronly (
  message_id bigint, chunk_idx int, session_uuid text, project text,
  ts timestamptz, snippet text, embedding vector(768),
  PRIMARY KEY (message_id, chunk_idx));
CREATE TABLE IF NOT EXISTS spike.emb_gemma512_userasst (
  message_id bigint, chunk_idx int, session_uuid text, project text,
  ts timestamptz, snippet text, embedding vector(768),
  PRIMARY KEY (message_id, chunk_idx));
GRANT ALL ON spike.emb_gemma512_useronly TO session_ingest;
GRANT ALL ON spike.emb_gemma512_userasst TO session_ingest;
