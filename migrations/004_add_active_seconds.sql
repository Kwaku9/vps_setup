-- ============================================================================
-- 004_add_active_seconds.sql
--
-- Adds sessions.sessions.active_seconds: "active working time" per session,
-- as opposed to the existing duration_seconds (raw wall-clock span from the
-- first to the last event, which counts every idle/away minute).
--
-- DEFINITION
--   active_seconds = Σ min(gap_between_consecutive_events, IDLE_CAP)
--   over the session's sessions.messages rows ordered by timestamp.
--   A gap under the cap counts fully (you were working); a gap over the cap is
--   clipped to the cap (you stepped away — only the head of the pause counts).
--
--   IDLE_CAP = 900 s (15 min). Chosen 2026-07-05. Changing it means re-running
--   this backfill AND updating IDLE_CAP_SECONDS in tools/ingest-sessions.py so
--   newly-ingested sessions stay consistent with historical ones.
--
-- PARITY: the gap population here (sessions.messages timestamps) is exactly the
--   set of rows tools/ingest-sessions.py writes to sessions.messages, so the
--   forward-compute in ingest and this backfill produce identical numbers.
--
-- ADDITIVE & SAFE: duration_seconds is left untouched (≈12 Grafana panels read
--   it as "session duration"). This only adds a new column. Reversible with
--   ALTER TABLE sessions.sessions DROP COLUMN active_seconds;
--
-- Transactional, ROLLBACK by default (dry-run). Flip trailing ROLLBACK->COMMIT
-- to apply. Idempotent (ADD COLUMN IF NOT EXISTS + full recompute UPDATE).
--
-- STATUS: applied to prod `enterprise` DB on 2026-07-05 (716 substantive
-- sessions: 18952.0 wall-clock hrs -> 1356.8 active hrs @ 15-min cap; sanity
-- check clean). Kept ROLLBACK-by-default for safe idempotent re-runs.
-- ============================================================================

BEGIN;

ALTER TABLE sessions.sessions
    ADD COLUMN IF NOT EXISTS active_seconds double precision;

-- Recompute for every session from its message timestamps.
WITH ev AS (
    SELECT session_id,
           timestamp,
           LAG(timestamp) OVER (PARTITION BY session_id ORDER BY timestamp) AS prev
    FROM sessions.messages
),
active AS (
    SELECT session_id,
           SUM(LEAST(EXTRACT(EPOCH FROM (timestamp - prev)), 900)) AS secs
    FROM ev
    WHERE prev IS NOT NULL
      AND timestamp > prev
    GROUP BY session_id
)
UPDATE sessions.sessions s
SET active_seconds = COALESCE(a.secs, 0)
FROM active a
WHERE a.session_id = s.id;

-- Sessions with 0 or 1 messages have no gaps -> no row in `active` -> set to 0
-- (distinguish "computed, no active time" from a future NULL "not yet computed").
UPDATE sessions.sessions
SET active_seconds = 0
WHERE active_seconds IS NULL;

-- ---- DRY-RUN OUTPUT ----
\echo '--- active vs wall-clock hours (substantive sessions, total_messages > 4) ---'
SELECT
    count(*)                                        AS sessions,
    ROUND((SUM(duration_seconds) / 3600.0)::numeric, 1) AS wallclock_hrs,
    ROUND((SUM(active_seconds)   / 3600.0)::numeric, 1) AS active_hrs
FROM sessions.sessions
WHERE total_messages > 4;

\echo '--- sanity: active_seconds must never exceed duration_seconds ---'
SELECT count(*) AS rows_where_active_gt_wallclock
FROM sessions.sessions
WHERE active_seconds > duration_seconds + 1;   -- +1s tolerance for rounding

ROLLBACK;
-- COMMIT;
