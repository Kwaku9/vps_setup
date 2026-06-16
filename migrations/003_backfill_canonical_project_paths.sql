-- ============================================================================
-- 003_backfill_canonical_project_paths.sql
--
-- One-time backfill/merge that repairs the Project rows shredded by the
-- decode_project_path() bug (see session-ingestion/ingest-sessions.py).
--
-- The authoritative project path for a session is the dominant `cwd` of its
-- messages (sessions.messages.cwd) -- NOT the lossy encoded projects-dir name.
-- This migration rebuilds canonical Project rows from cwd, re-points sessions
-- and git_repos onto them, and deletes the now-unreferenced mangled rows.
--
-- PREREQUISITES (run in order)
--   * 001_repair_project_path_unique_index.sql -- the ON CONFLICT + path joins
--     below require a HEALTHY unique index; 001 dedups + reindexes it first.
--   * 002_prune_empty_session_shells.sql -- so the shells' cwd-less mangled
--     projects fall out as unreferenced and get cleaned up by step 6 here.
--   * Deploy the ingest-sessions.py fix FIRST (so new ingests stop creating
--     mangled rows; otherwise this migration is undone on the next run).
--
-- SAFETY
--   * Wrapped in a transaction; ends with ROLLBACK by default. Inspect the
--     dry-run output, then change the final ROLLBACK to COMMIT and re-run.
--   * Re-runnable / idempotent: MERGE-by-cwd + delete-unreferenced converge.
--   * FK note: sessions.git_repos.project_id is ON DELETE NO ACTION, so repos
--     are re-pointed (step 5) BEFORE the delete (step 6).
--
-- Expected outcome on the data inspected 2026-06-15: 42 -> ~27 Project rows,
-- vps_setup history reunited within each machine (cross-machine rollup is the
-- separate :Codebase projection layer, not this migration).
-- ============================================================================

BEGIN;

-- 1. Authoritative path per session = dominant non-empty cwd of its messages.
CREATE TEMP TABLE session_cwd ON COMMIT DROP AS
SELECT session_id,
       mode() WITHIN GROUP (ORDER BY cwd) AS cwd
FROM sessions.messages
WHERE cwd IS NOT NULL AND cwd <> ''
GROUP BY session_id;

-- 2. Upsert one canonical Project per distinct cwd. display_name = last path
--    segment (handles both '/' and '\' separators; split_part neg idx needs PG14+).
INSERT INTO sessions.projects (project_path, display_name, source)
SELECT DISTINCT ON (sc.cwd)
       sc.cwd,
       split_part(rtrim(replace(sc.cwd, '\', '/'), '/'), '/', -1),
       s.source
FROM session_cwd sc
JOIN sessions.sessions s ON s.id = sc.session_id
ORDER BY sc.cwd, s.id
ON CONFLICT (project_path) DO UPDATE SET display_name = EXCLUDED.display_name;

-- 3. old project_id -> canonical project_id (majority vote of the old project's
--    sessions). Used to move git_repos, which carry no cwd of their own.
CREATE TEMP TABLE proj_remap ON COMMIT DROP AS
SELECT DISTINCT ON (s.project_id) s.project_id AS old_id, p.id AS new_id
FROM sessions.sessions s
JOIN session_cwd sc ON sc.session_id = s.id
JOIN sessions.projects p ON p.project_path = sc.cwd
GROUP BY s.project_id, p.id
ORDER BY s.project_id, count(*) DESC;

-- 4. Re-point sessions directly onto their canonical (cwd) project.
UPDATE sessions.sessions s
SET project_id = p.id
FROM session_cwd sc
JOIN sessions.projects p ON p.project_path = sc.cwd
WHERE s.id = sc.session_id
  AND s.project_id IS DISTINCT FROM p.id;

-- 5. Re-point git_repos off any mangled project (must precede the delete).
UPDATE sessions.git_repos r
SET project_id = rm.new_id
FROM proj_remap rm
WHERE r.project_id = rm.old_id
  AND r.project_id IS DISTINCT FROM rm.new_id;

-- 6. Delete now-unreferenced (mangled) Project rows.
DELETE FROM sessions.projects p
WHERE NOT EXISTS (SELECT 1 FROM sessions.sessions s  WHERE s.project_id = p.id)
  AND NOT EXISTS (SELECT 1 FROM sessions.git_repos r WHERE r.project_id = p.id);

-- ---- DRY-RUN OUTPUT (review before committing) ----------------------------
\echo '--- projects remaining ---'
SELECT count(*) AS projects_remaining FROM sessions.projects;
\echo '--- canonical project rows (expect clean paths, no -home-... / .../vps/setup) ---'
SELECT id, project_path, display_name, source FROM sessions.projects ORDER BY project_path;
\echo '--- any sessions still on a non-cwd (fallback-decoded) project? ---'
SELECT count(*) AS sessions_without_cwd_link
FROM sessions.sessions s
WHERE NOT EXISTS (SELECT 1 FROM session_cwd sc WHERE sc.session_id = s.id);

-- Flip to COMMIT once the dry-run looks right.
ROLLBACK;
-- COMMIT;
