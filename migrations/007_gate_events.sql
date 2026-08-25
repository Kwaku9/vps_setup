-- ============================================================================
-- 007_gate_events.sql
--
-- Creates sessions.gate_events: the queryable home for gate decisions recorded
-- live by ~/.claude/hooks/gate_ledger.py.
--
-- WHY THIS EXISTS SEPARATELY FROM 006
--   006 reclassifies historical tool_calls, recovering denials that were already
--   sitting in the record mislabelled as errors. It can only see what the
--   transcript happened to preserve, and only for calls that actually reached a
--   tool_result.
--
--   This table holds what the hook observes directly, which is strictly more:
--     - the permission PROMPT being raised, which has no tool_result at all and
--       is therefore invisible to 006. That row is what makes human decision
--       latency measurable on the local plane, the way gateway.approvals already
--       makes it measurable on the remote one.
--     - denials on calls whose transcript was never ingested or has aged out.
--
--   Two sources, deliberately. 006 is archaeology and this is telemetry. They
--   should agree about the overlap, and a disagreement is a signal worth having
--   rather than a bug to paper over, so neither overwrites the other.
--
-- WHAT IS NOT STORED
--   No tool input. Half of all tool calls in this estate are Bash and an August
--   2026 audit found 42 live credentials in the corpus with command literals as
--   the dominant vector. Storing commands here would mint a second permanent
--   copy of that exposure in a table whose purpose is to be retained forever.
--   input_sha256 correlates a row to its session record without doing that.
--
-- ADDITIVE & SAFE: creates one table, touches nothing existing.
--   Reversible: DROP TABLE sessions.gate_events;
--
-- Transactional, ROLLBACK by default (dry-run). Flip trailing ROLLBACK->COMMIT
-- to apply. Idempotent (CREATE TABLE IF NOT EXISTS).
--
-- STATUS: applied to prod `enterprise` DB on 2026-08-25. Table created and loaded
-- from the live ledger: 9 gate events (user 7, classifier 2), including both
-- classifier denials raised while this work was being done. Re-running the
-- ingester inserted 0, so the natural key holds against real data.
-- Kept ROLLBACK-by-default for safe idempotent re-runs.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS sessions.gate_events (
    id              bigserial PRIMARY KEY,
    ts              timestamptz NOT NULL,
    session_uuid    text,
    tool_use_id     text,
    tool_name       text,
    -- 'denied' (a gate refused) or 'prompt' (approval was requested)
    event           text NOT NULL,
    -- user | classifier | rule | safety | awaiting_human
    reason          text,
    cwd             text,
    input_sha256    text,
    -- redacted preview only, never the raw command
    detail          text,
    ingested_at     timestamptz NOT NULL DEFAULT now(),

    -- The ledger is append-only and the ingester is re-runnable, so the same
    -- line must not land twice. A gate event is uniquely identified by when it
    -- happened, which call it concerned, and what kind of event it was.
    CONSTRAINT gate_events_natural_key UNIQUE (ts, event, tool_use_id, session_uuid)
);

CREATE INDEX IF NOT EXISTS idx_gate_events_ts      ON sessions.gate_events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_gate_events_reason  ON sessions.gate_events (reason);
CREATE INDEX IF NOT EXISTS idx_gate_events_session ON sessions.gate_events (session_uuid);

-- ---- DRY-RUN OUTPUT -------------------------------------------------------
\echo '--- table shape ---'
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'sessions' AND table_name = 'gate_events'
ORDER BY ordinal_position;

\echo '--- CONTROL: the natural key must actually reject a duplicate ---'
-- If this constraint is not doing its job, re-running the ingester silently
-- doubles every count and the resulting denial rate is fiction.
SAVEPOINT dup_probe;
INSERT INTO sessions.gate_events (ts, session_uuid, tool_use_id, event, reason)
VALUES ('2000-01-01T00:00:00Z', 'probe', 'probe', 'denied', 'rule');
INSERT INTO sessions.gate_events (ts, session_uuid, tool_use_id, event, reason)
VALUES ('2000-01-01T00:00:00Z', 'probe', 'probe', 'denied', 'rule')
ON CONFLICT ON CONSTRAINT gate_events_natural_key DO NOTHING;
SELECT count(*) AS probe_rows_expected_1
FROM sessions.gate_events WHERE session_uuid = 'probe';
ROLLBACK TO SAVEPOINT dup_probe;

ROLLBACK;
-- COMMIT;
