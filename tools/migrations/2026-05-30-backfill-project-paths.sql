-- ============================================================================
-- Backfill: correct corrupted sessions.projects.project_path values
-- ============================================================================
--
-- WHY
--   ingest-sessions.py used to reconstruct project paths from Claude Code's
--   encoded directory slug via a blind replace("-", "/"). The slug is lossy: a
--   '-' could originally have been '/', '_', or a literal hyphen. So
--     /workspace/vscode-projects/vps_setup
--   was stored as
--     /workspace/vscode/projects/vps/setup
--   and the Windows-era equivalents were split the same way. The ingest script
--   has since been fixed to read the authoritative cwd from the session records
--   (read_project_cwd()), but rows ingested before the fix are still corrupted.
--
-- WHAT THIS DOES
--   1. Computes the authoritative path for each project from the cwd already
--      stored on its messages (sessions.messages.cwd) -- no JSONL needed.
--   2. Groups projects that resolve to the SAME canonical path (these are
--      duplicates: same workspace ingested under different decoded paths, or
--      the same repo seen from VPS and Windows). One survivor per group.
--   3. Re-points sessions (and git_repos) from the duplicates onto the survivor.
--   4. Rewrites the survivor's project_path + display_name to the canonical
--      value, then deletes the now-empty duplicate project rows.
--
-- SAFETY
--   * Fully transactional: BEGIN/COMMIT. Any error rolls back the whole thing.
--   * Idempotent: re-running is a no-op once paths are already canonical.
--   * Non-destructive to sessions/messages -- only re-points FKs and deletes
--      empty duplicate project rows.
--   * Projects whose messages carry no cwd (e.g. only progress records, or an
--      empty dir) are left untouched -- nothing authoritative to fix them with.
--
-- HOW TO RUN
--   Preview first (no writes):
--     psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 2026-05-30-backfill-project-paths.sql --set=apply=0
--   Apply:
--     psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 2026-05-30-backfill-project-paths.sql --set=apply=1
--   (Requires the SSH tunnel to the VPS Postgres to be up.)
--
--   After applying, re-run the Neo4j ETL to propagate the corrected rows:
--     cd ../../local/etl && python sync_sessions_to_neo4j.py --fresh
-- ============================================================================

\set ON_ERROR_STOP on
-- default `apply` to 0 (preview) if the caller did not pass it
\if :{?apply}
\else
  \set apply 0
\endif

-- Comma-separated project ids to leave untouched. Use for rows where the slug
-- and the dominant cwd genuinely disagree (the slug points at an ANCESTOR dir,
-- not the same dir whose separators were mangled) -- e.g. 653 (-home-general),
-- whose messages' dominant cwd is .../fedora-workstation. Default: none.
\if :{?skip_ids}
\else
  \set skip_ids ''
\endif

BEGIN;

-- ── 1. Authoritative path per project, from the cwd on its messages ─────────
-- Most frequently recorded non-empty cwd wins; ties broken deterministically.
CREATE TEMP TABLE _project_canonical ON COMMIT DROP AS
WITH cwd_counts AS (
    SELECT s.project_id,
           m.cwd,
           count(*) AS n
    FROM sessions.sessions s
    JOIN sessions.messages m ON m.session_id = s.id
    WHERE m.cwd IS NOT NULL
      AND length(trim(m.cwd)) > 0
    GROUP BY s.project_id, m.cwd
),
ranked AS (
    SELECT project_id,
           trim(cwd) AS cwd,
           row_number() OVER (
               PARTITION BY project_id
               ORDER BY n DESC, trim(cwd)
           ) AS rn
    FROM cwd_counts
)
SELECT project_id,
       cwd AS canonical_path,
       -- last path segment: strip trailing separators, then drop everything up
       -- to and including the final / or \ (handles both POSIX and Windows cwds)
       regexp_replace(regexp_replace(cwd, '[/\\]+$', ''), '^.*[/\\]', '') AS canonical_display_name
FROM ranked
WHERE rn = 1;

-- ── 2. One survivor project per canonical path (lowest id wins) ─────────────
CREATE TEMP TABLE _survivor ON COMMIT DROP AS
SELECT canonical_path,
       min(project_id) AS survivor_id
FROM _project_canonical
GROUP BY canonical_path;

-- ── 3. Map every project -> its survivor + canonical values ─────────────────
CREATE TEMP TABLE _remap ON COMMIT DROP AS
SELECT pc.project_id AS old_id,
       sv.survivor_id,
       pc.canonical_path,
       pc.canonical_display_name
FROM _project_canonical pc
JOIN _survivor sv USING (canonical_path);

-- ── 3b. Absorb collision projects ───────────────────────────────────────────
-- A project that carries no cwd of its own (so it's absent from _remap) might
-- already sit on the exact path a survivor is about to claim. Rewriting the
-- survivor onto that path would then trip the project_path UNIQUE constraint.
-- Fold any such project into the merge instead: its sessions get re-pointed and
-- the empty row is deleted before the survivor is rewritten, so no collision.
INSERT INTO _remap (old_id, survivor_id, canonical_path, canonical_display_name)
SELECT p.id,
       sv.survivor_id,
       sv.canonical_path,
       regexp_replace(regexp_replace(sv.canonical_path, '[/\\]+$', ''), '^.*[/\\]', '')
FROM sessions.projects p
JOIN _survivor sv ON sv.canonical_path = p.project_path
WHERE p.id <> sv.survivor_id
  AND p.id NOT IN (SELECT old_id FROM _remap);

-- ── 3c. Projects to leave untouched (from --set=skip_ids=...) ────────────────
CREATE TEMP TABLE _skip_projects ON COMMIT DROP AS
SELECT x::int AS project_id
FROM unnest(string_to_array(:'skip_ids', ',')) AS x
WHERE length(trim(x)) > 0;

-- A skipped project must not be merged away or rewritten. Drop it from _remap
-- both as a source (old_id) and as a survivor target (survivor_id).
DELETE FROM _remap
WHERE old_id IN (SELECT project_id FROM _skip_projects)
   OR survivor_id IN (SELECT project_id FROM _skip_projects);

-- ── Preview: what would change ──────────────────────────────────────────────
\echo ''
\echo '=== Projects being SKIPPED (--set=skip_ids) ==='
SELECT p.id, p.project_path AS current_path, p.display_name
FROM sessions.projects p
JOIN _skip_projects sk ON sk.project_id = p.id
ORDER BY p.id;

\echo ''
\echo '=== Projects whose stored path differs from the authoritative cwd ==='
SELECT p.id,
       p.project_path        AS current_path,
       r.canonical_path      AS corrected_path,
       (r.old_id <> r.survivor_id) AS is_duplicate_merged_away,
       r.survivor_id
FROM _remap r
JOIN sessions.projects p ON p.id = r.old_id
WHERE p.project_path IS DISTINCT FROM r.canonical_path
   OR r.old_id <> r.survivor_id
ORDER BY r.canonical_path, p.id;

\echo ''
\echo '=== Duplicate groups (multiple project rows -> one canonical path) ==='
SELECT canonical_path,
       count(*)                       AS project_rows,
       array_agg(project_id ORDER BY project_id) AS project_ids,
       min(project_id)                AS survivor_id
FROM _project_canonical
GROUP BY canonical_path
HAVING count(*) > 1
ORDER BY canonical_path;

-- ── 4. Apply (only when --set=apply=1) ──────────────────────────────────────
\if :apply

  \echo ''
  \echo '>>> apply=1 : re-pointing FKs and rewriting paths'

  -- 4a. Re-point sessions from duplicates onto the survivor
  UPDATE sessions.sessions s
  SET project_id = r.survivor_id
  FROM _remap r
  WHERE s.project_id = r.old_id
    AND r.old_id <> r.survivor_id;

  -- 4b. Re-point git_repos likewise (FK references sessions.projects(id))
  UPDATE sessions.git_repos g
  SET project_id = r.survivor_id
  FROM _remap r
  WHERE g.project_id = r.old_id
    AND r.old_id <> r.survivor_id;

  -- 4c. Delete the now-empty duplicate project rows (survivors excluded)
  DELETE FROM sessions.projects p
  USING _remap r
  WHERE p.id = r.old_id
    AND r.old_id <> r.survivor_id;

  -- 4d. Rewrite survivors to the canonical path + display name
  UPDATE sessions.projects p
  SET project_path = r.canonical_path,
      display_name = r.canonical_display_name
  FROM _remap r
  WHERE p.id = r.survivor_id
    AND r.old_id = r.survivor_id
    AND (p.project_path IS DISTINCT FROM r.canonical_path
         OR p.display_name IS DISTINCT FROM r.canonical_display_name);

  \echo '>>> done. Verifying no remaining corrupted survivors...'
  SELECT count(*) AS remaining_mismatches
  FROM _remap r
  JOIN sessions.projects p ON p.id = r.survivor_id
  WHERE p.project_path IS DISTINCT FROM r.canonical_path;

  COMMIT;
  \echo '>>> COMMITTED.'

\else

  \echo ''
  \echo '>>> preview only (apply=0). No changes written. Re-run with --set=apply=1 to apply.'
  ROLLBACK;

\endif
