-- Session summary layer for the buildfol.io widget and the recall/claims index.
--
-- Applied to the `enterprise` database on 2026-08-11. Kept here so the schema is
-- reproducible rather than existing only as an ad-hoc change on the box:
--   psql -U "$POSTGRES_USER" -d enterprise -v ON_ERROR_STOP=1 -f session_summaries.sql
--
-- visibility DEFAULTS TO 'private' and that is load-bearing. The widget must only
-- ever read WHERE visibility='public'. A row becomes public only when the model
-- judged the session non-sensitive AND a local deny-list also passed -- see
-- tools/summarize-sessions.py. Default-deny is the whole point: a wrongly-private
-- summary costs nothing, a wrongly-public one is a leak.
--
-- session_uuid is the anchor back to sessions.sessions, so any claim the widget
-- makes can be traced to the evidence it came from.

CREATE TABLE IF NOT EXISTS sessions.session_summaries (
    session_uuid  text PRIMARY KEY,
    one_liner     text NOT NULL,          -- <= ~90 chars; what the widget injects
    paragraph     text,                   -- 2-3 sentences; for follow-up questions
    visibility    text NOT NULL DEFAULT 'private',
    redact_reason text,                   -- which gate forced private, for auditing
    model         text,                   -- so a subset can be regenerated later
    generated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT session_summaries_visibility_ck
        CHECK (visibility IN ('private','public'))
);

CREATE INDEX IF NOT EXISTS session_summaries_visibility_idx
    ON sessions.session_summaries (visibility);

CREATE INDEX IF NOT EXISTS session_summaries_generated_idx
    ON sessions.session_summaries (generated_at DESC);
