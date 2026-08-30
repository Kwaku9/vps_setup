-- ============================================================================
-- 006_tool_call_denied_status.sql
--
-- Adds a `denied` terminal status to sessions.tool_calls, plus a
-- denial_reason column saying which gate refused, and reclassifies the
-- historical rows that are currently mislabelled as errors.
--
-- WHY
--   status was derived from a single bit, the tool_result is_error flag, so two
--   unrelated events collapsed into "error":
--       a command that ran and failed   (the agent did something and it broke)
--       a command a gate refused to run (the agent was stopped)
--   The second is the record of governance working. With no way to tell them
--   apart, "how often did the gate fire" is unanswerable, and any claim that
--   agents run under human approval has no evidence behind it.
--
--   Measured 2026-08-25 against the production graph: a query for any
--   denied/rejected/blocked status returned 0 rows, while the raw JSONL held
--   304 explicit refusals across 894 is_error results. One in three recorded
--   "errors" was the gate doing its job.
--
-- REASON VOCABULARY (matches tools/gate_classify.py, which is the single source
-- of truth and is imported by both the live hook and ingest-sessions.py):
--       user        a human refused the action interactively
--       classifier  auto-mode classifier blocked it before it ran
--       rule        no permission rule covered it, so it needed approval
--       safety      refused on command shape (obfuscation, unsafe expansion)
--
-- WHY THE PATTERNS ARE ANCHORED
--   "requires approval" is ordinary English and appears in agent prose that has
--   nothing to do with a gate. The classifier's own self-test caught a loose
--   pattern matching exactly that. The SQL below mirrors the anchored forms.
--   Misfiling a denial as an error understates governance; misfiling an error as
--   a denial would overstate it, so every ambiguous case stays an error.
--
-- ADDITIVE & SAFE: no column is dropped and no row is deleted. Panels reading
--   status = 'error' will see their counts fall, which is the intended
--   correction and the reason this migration prints the before/after delta.
--   Reversible: UPDATE ... SET status='error', denial_reason=NULL WHERE
--   status='denied'; then ALTER TABLE ... DROP COLUMN denial_reason;
--
-- Transactional, ROLLBACK by default (dry-run). Flip trailing ROLLBACK->COMMIT
-- to apply. Idempotent (ADD COLUMN IF NOT EXISTS + recompute from result_text).
--
-- STATUS: applied to prod `enterprise` DB on 2026-08-25. 150 rows reclassified
-- (user 74, classifier 71, safety 5); error 3800 -> 3650; success and pending
-- unchanged at 63,075 and 24,343. All three controls passed, and the result was
-- re-read on a fresh connection rather than trusted from inside the transaction.
-- Kept ROLLBACK-by-default for safe idempotent re-runs.
--
-- REVERSAL: the 150 affected ids were captured before applying. Nothing was
-- 'denied' beforehand (verified 0), so the inverse is exact:
--   UPDATE sessions.tool_calls SET status='error', denial_reason=NULL
--   WHERE status='denied';
-- ============================================================================

BEGIN;

ALTER TABLE sessions.tool_calls
    ADD COLUMN IF NOT EXISTS denial_reason text;

-- Partial index: denials are a small, frequently-filtered slice. Indexing the
-- whole status column would be wasted on the 68% that are 'success'.
CREATE INDEX IF NOT EXISTS idx_tool_calls_denied
    ON sessions.tool_calls (timestamp)
    WHERE status = 'denied';

-- ---- reclassify -----------------------------------------------------------
-- Only rows already marked 'error' are eligible. A successful result is never a
-- denial, and scanning success text for these phrases would match an agent
-- merely discussing permissions.
WITH classified AS (
    SELECT
        id,
        CASE
            -- ordinary tool misuse that reads like a refusal but no gate decided
            WHEN result_text ~* '(file has not been read yet|has been modified since read|string to replace not found|no such file or directory)'
                THEN NULL
            WHEN result_text ~* '(user doesn''t want to proceed with this tool use|the tool use was rejected)'
                THEN 'user'
            WHEN result_text ~* 'permission for this action was denied by the claude code auto mode classifier'
                THEN 'classifier'
            WHEN result_text ~* '(requested permissions to use \w+, but you haven''t granted it yet)'
                 OR result_text ~* '^this command requires approval'
                 OR result_text ~* '^this bash command contains multiple operations'
                 OR result_text ~* '^claude requested permissions'
                THEN 'rule'
            WHEN result_text ~* '(expansion obfuscation|contains brace with quote character|command injection)'
                THEN 'safety'
            ELSE NULL
        END AS reason
    FROM sessions.tool_calls
    WHERE status = 'error'
      AND result_text IS NOT NULL
)
UPDATE sessions.tool_calls t
SET status = 'denied',
    denial_reason = c.reason
FROM classified c
WHERE c.id = t.id
  AND c.reason IS NOT NULL;

-- ---- DRY-RUN OUTPUT -------------------------------------------------------
\echo '--- status distribution after reclassification ---'
SELECT status,
       count(*)                                                   AS calls,
       ROUND(100.0 * count(*) / SUM(count(*)) OVER (), 1)         AS pct
FROM sessions.tool_calls
GROUP BY status
ORDER BY calls DESC;

\echo '--- denials by reason (the number that did not exist before) ---'
SELECT denial_reason, count(*) AS calls
FROM sessions.tool_calls
WHERE status = 'denied'
GROUP BY denial_reason
ORDER BY calls DESC;

\echo '--- which tools get stopped most ---'
SELECT tool_name, count(*) AS denied
FROM sessions.tool_calls
WHERE status = 'denied'
GROUP BY tool_name
ORDER BY denied DESC
LIMIT 10;

-- ---- CONTROLS -------------------------------------------------------------
-- A reclassification that moved everything would also "succeed" on the check
-- above. These two must both hold or the migration is wrong.

\echo '--- CONTROL 1: genuine failures must SURVIVE as errors (expect > 0) ---'
SELECT count(*) AS still_errors_expected_nonzero
FROM sessions.tool_calls
WHERE status = 'error';

\echo '--- CONTROL 2: no denial may lack a reason (expect 0) ---'
SELECT count(*) AS denied_without_reason_expected_zero
FROM sessions.tool_calls
WHERE status = 'denied' AND denial_reason IS NULL;

\echo '--- CONTROL 3: exit-code failures must NEVER be denials (expect 0) ---'
SELECT count(*) AS exitcode_rows_marked_denied_expected_zero
FROM sessions.tool_calls
WHERE status = 'denied'
  AND result_text ~* '^exit code \d';

ROLLBACK;
-- COMMIT;
