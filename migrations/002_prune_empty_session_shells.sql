-- ============================================================================
-- 002_prune_empty_session_shells.sql
--
-- Deletes zero-message Session shells (spec item 3). As inspected 2026-06-15:
-- 14 sessions with no messages. They carry no tool_calls/artifacts/subagents.
--
-- git_commits: 18 commits are linked to 4 of these shells, but
-- git_commits.session_id is ON DELETE SET NULL -- so deleting a shell PRESERVES
-- the commits (their session_id goes NULL) and the next git-history ingest's
-- correlate_sessions() re-links them to real message-bearing sessions. No git
-- history is lost.
--
-- Durable: the current ingest never inserts zero-message sessions
-- (parse_session_file returns None when total_messages == 0), and the git-history
-- ingester does not insert session rows -- so pruned shells do not respawn.
--
-- SAFETY: transactional, ROLLBACK by default. Idempotent.
-- ORDER: run AFTER 001 (healthy index) and BEFORE 003 (backfill), so the shells'
-- mangled project rows fall out as unreferenced and 003 cleans them up.
-- ============================================================================

BEGIN;

-- Commits this prune will detach (SET NULL) -- captured BEFORE the delete so the
-- count is the true delta, not the table-wide total of NULLs.
\echo '--- commits attached to shells being pruned (will SET NULL, re-correlate next git ingest) ---'
SELECT count(*) AS commits_detached_by_prune
FROM sessions.git_commits c
WHERE c.session_id IN (
    SELECT s.id FROM sessions.sessions s
    WHERE NOT EXISTS (SELECT 1 FROM sessions.messages m WHERE m.session_id = s.id)
);

-- Cascade FKs (messages/tool_calls/artifacts/subagents) are ON DELETE CASCADE,
-- but shells have none attached; git_commits.session_id is ON DELETE SET NULL.
DELETE FROM sessions.sessions s
WHERE NOT EXISTS (SELECT 1 FROM sessions.messages m WHERE m.session_id = s.id);

-- ---- DRY-RUN OUTPUT ----
\echo '--- remaining zero-message sessions (expect 0) ---'
SELECT count(*) AS empty_shells_remaining
FROM sessions.sessions s
WHERE NOT EXISTS (SELECT 1 FROM sessions.messages m WHERE m.session_id = s.id);

ROLLBACK;
-- COMMIT;
