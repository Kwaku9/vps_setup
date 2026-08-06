-- ---------------------------------------------------------------------------
-- reporting schema — the read-only analytical surface over LiteLLM's ledger.
--
-- Why a separate schema: LiteLLM runs `prisma migrate deploy` AND a
-- `prisma db execute` diff against schema.prisma on every boot. That diff only
-- knows about `public`, so anything we add there (indexes included) is liable
-- to be dropped underneath us. `reporting` is invisible to it.
--
-- Idempotent: safe to re-run on every deploy.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS reporting;

-- ---------------------------------------------------------------------------
-- reporting.spend — the ONE definition of spend.
--
-- Every Grafana cost panel reads this view and nothing else, so no two panels
-- can quietly disagree about what a dollar or a call means. Two normalizations
-- happen here and nowhere else:
--
--   provider   custom_llm_provider is blank on a large minority of rows. Fall
--              back to the model's routing prefix
--              ("openrouter/anthropic/claude-opus-4.5" -> "openrouter"), and
--              only call it 'unknown' when the model carries no prefix either.
--
--   has_usage  ~473 rows (health probes, TTS, image generation) record neither
--              tokens nor spend. They are KEPT rather than filtered out —
--              dropping them would undercount real calls — and flagged instead,
--              so each panel decides. Cost sums are unaffected either way,
--              since those rows contribute exactly $0.
--
-- Deliberately NOT exposed: messages, response, proxy_server_request. Those
-- JSONB columns hold raw prompt and completion text. The view is owned by the
-- app role and Postgres evaluates views with the owner's privileges, so a
-- grantee of this view cannot reach the base table through it.
-- ---------------------------------------------------------------------------

-- DROP before CREATE, not CREATE OR REPLACE: replacing a view cannot change a
-- column's data type, so any future change to a column expression here would
-- fail the deploy on an existing install. Grants are re-applied below.
DROP VIEW IF EXISTS reporting.spend;

CREATE VIEW reporting.spend AS
SELECT
    -- LiteLLM stores UTC in a `timestamp WITHOUT time zone`. Grafana's
    -- $__timeFilter / $__timeGroup compare against timestamptz, so an
    -- unqualified column silently shifts every window by the host's UTC offset
    -- (4h here). Stamp the zone the data is actually in, once, at the source.
    (s."startTime" AT TIME ZONE 'UTC')                   AS ts,
    s.request_id,
    NULLIF(s.call_type, '')                              AS call_type,
    s.model,
    COALESCE(
        NULLIF(s.custom_llm_provider, ''),
        NULLIF(split_part(s.model, '/', 1), s.model),
        'unknown'
    )                                                    AS provider,
    NULLIF(s.model_group, '')                            AS model_group,
    s.spend                                              AS usd,
    s.total_tokens,
    s.prompt_tokens,
    s.completion_tokens,
    NULLIF(s.end_user, '')                               AS end_user,
    NULLIF(s.team_id, '')                                AS team_id,
    NULLIF(s.api_key, '')                                AS api_key,
    (s.spend > 0 OR s.total_tokens > 0)                  AS has_usage,
    GREATEST(EXTRACT(EPOCH FROM (s."endTime" - s."startTime")), 0) AS latency_s
FROM public."LiteLLM_SpendLogs" s;

COMMENT ON VIEW reporting.spend IS
    'Canonical LiteLLM spend surface for Grafana. Normalizes provider, flags '
    'zero-usage rows, and withholds prompt/response payloads.';

-- ---------------------------------------------------------------------------
-- grafana_ro — least-privilege reader. Mirrors the role of the same name on
-- the shared `enterprise` database (see shared-services/files/pg-app-roles.sql)
-- and reuses the same vault password, since it is the same consumer.
--
-- Granted on the VIEW only. No grant on public."LiteLLM_SpendLogs", so prompt
-- and completion text stays out of reach even if a dashboard query is edited.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') THEN
        CREATE ROLE grafana_ro LOGIN;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE litellm TO grafana_ro;
GRANT USAGE  ON SCHEMA reporting TO grafana_ro;
GRANT SELECT ON reporting.spend  TO grafana_ro;

-- Belt and braces: make sure a future CREATE OR REPLACE cannot silently widen
-- access, and that grafana_ro never picks up the base table by default.
REVOKE ALL ON public."LiteLLM_SpendLogs" FROM grafana_ro;
REVOKE ALL ON SCHEMA public FROM grafana_ro;
