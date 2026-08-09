-- 005: stop recall.chunks from accumulating orphaned duplicate vectors.
--
-- THE BUG
-- -------
-- ingest-sessions.py re-imports a session whenever its JSONL size changes:
--
--     if existing and existing[1] == file_size:  continue        # unchanged, skip
--     if existing:  DELETE FROM sessions.sessions WHERE id = ...  # changed, re-import
--
-- That DELETE cascades to sessions.messages, which get NEW ids on re-insert.
-- recall.chunks references messages.id but had NO foreign key, so the old rows
-- survived pointing at ids that no longer exist. The re-imported messages then
-- had no chunks, so the nightly embedder re-embedded them -- adding a second full
-- copy. Every subsequent re-import added another.
--
-- MEASURED 2026-08-09 (recall-eval-pg, a byte copy of production):
--   recall.chunks total            102,881
--     resolving to a live message   67,864
--     ORPHANED                      35,017   (34.0%)
--   exact-duplicate snippet rows    42,417   (41.2%)
--   sessions affected                   71   (all of which ALSO have live chunks,
--                                             i.e. every orphan is a true duplicate)
--   worst case: one session with 7,708 chunks for 948 distinct snippets -- 8 copies.
--
-- WHY IT MATTERS BEYOND WASTED SPACE
-- ----------------------------------
-- recall.py never joins messages (it reads recall.chunks and joins only
-- sessions.sessions on session_uuid), so orphans ARE returned by search. They are
-- near-identical vectors that tie at ~0 distance and crowd the neighbourhood.
-- This is the documented CourtListener failure mode ("0/9 found, index broken"
-- caused by duplicate vectors tying at distance 0), and it mechanically explains
-- Phase 0 Finding 2: prefetch pulls k*20 chunks, DISTINCT ON (session_uuid)
-- collapses the duplicates, and the candidate pool lands at a median of 5
-- sessions against a requested k=8.
--
-- ORDER MATTERS: the orphans must be deleted BEFORE the FK is added, or the
-- constraint cannot validate.

BEGIN;

-- 1. Delete orphaned chunks: those whose message no longer exists.
--
-- Scope note: this removes ONLY chunks with no live message. It deliberately does
-- NOT touch duplicate snippet text among LIVE messages (~7,400 rows). Identical
-- text in two different live messages is real data -- usually repeated harness
-- boilerplate -- and deleting it would drop genuine rows. Treat that separately
-- as a pre-processing/boilerplate-stripping decision, not as corruption cleanup.
DELETE FROM recall.chunks c
WHERE NOT EXISTS (
    SELECT 1 FROM sessions.messages m WHERE m.id = c.message_id
);

-- 2. Prevent recurrence at the database level rather than in Python.
--
-- A code fix in ingest-sessions.py would work until someone deletes a session by
-- hand, adds a second writer, or reverts the file. The constraint cannot be
-- forgotten. From here, deleting a session cascades sessions -> messages -> chunks,
-- and the embedder's `NOT EXISTS (... FROM recall.chunks ...)` delta then re-embeds
-- the re-imported messages exactly once.
ALTER TABLE recall.chunks
    ADD CONSTRAINT chunks_message_id_fkey
    FOREIGN KEY (message_id) REFERENCES sessions.messages(id) ON DELETE CASCADE;

-- 3. CONTROL: assert the table is actually clean before committing.
--    A migration that "succeeded" while leaving orphans behind is worse than one
--    that failed loudly, because the FK would then be the only thing holding the
--    line and nobody would know the backlog was still there.
DO $$
DECLARE n bigint;
BEGIN
    SELECT count(*) INTO n
    FROM recall.chunks c
    WHERE NOT EXISTS (SELECT 1 FROM sessions.messages m WHERE m.id = c.message_id);
    IF n <> 0 THEN
        RAISE EXCEPTION 'CONTROL FAILED: % orphaned chunks remain after cleanup', n;
    END IF;
END $$;

COMMIT;

-- 4. Unique index enabling the result_text backfill (and future upserts).
--    (session_id, tool_use_id) is already unique in the data -- 78,701 rows,
--    78,701 distinct pairs -- but was never indexed. CONCURRENTLY cannot run
--    inside a transaction block, hence after COMMIT.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_tool_calls_session_tuid
    ON sessions.tool_calls (session_id, tool_use_id);
