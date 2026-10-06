-- 010: index the foreign key sessions.tool_calls.message_id.
--
-- tool_calls.message_id references sessions.messages(id) ON DELETE CASCADE but
-- had no index, so every deleted message (each routine session re-import, and
-- any cleanup) cascaded with a full scan of tool_calls (529 MB on 2026-10-06).
-- A 64k-row delete would have taken hours; with the index a 500-row batch takes
-- about 50 ms. Applied on the VPS 2026-10-06.
--
--   podman exec -i postgres psql -U postgres -d enterprise < 010_tool_calls_message_id_index.sql
SET lock_timeout = '10s';
CREATE INDEX CONCURRENTLY IF NOT EXISTS tool_calls_message_id_idx
    ON sessions.tool_calls (message_id);
