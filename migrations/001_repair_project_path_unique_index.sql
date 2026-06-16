-- ============================================================================
-- 001_repair_project_path_unique_index.sql
--
-- Repairs a CORRUPT unique index on sessions.projects(project_path).
--
-- Symptom: projects_project_path_key reports valid/ready/live, yet byte-identical
-- duplicate project_path rows exist (same md5, same octet_length). A live UNIQUE
-- btree cannot legitimately hold byte-identical duplicates -- the index is out of
-- sync with the heap. This is the classic signature of a glibc/ICU collation
-- change (the projects' text comparisons shifted under the index after a libc
-- upgrade in the container base image / data-dir move).
--
-- WHY FIRST: migration 003 (backfill) uses ON CONFLICT (project_path) and joins
-- sessions to projects on project_path. Both misbehave while duplicate rows and a
-- corrupt index exist, so this must run BEFORE 003.
--
-- SAFETY: transactional, ROLLBACK by default. REINDEX (non-concurrent) is
-- transactional and rolls back with the rest during the dry-run.
--
-- BROADER RISK: a collation change corrupts *every* collation-sensitive text
-- index, not just this one. After committing, schedule a full
-- `REINDEX DATABASE enterprise;` in a maintenance window (amcheck can confirm
-- which indexes are affected). This migration only fixes the one with known dups.
-- ============================================================================

BEGIN;

-- 1. For each project_path, keep the lowest id; the rest are duplicates to remove.
CREATE TEMP TABLE proj_dedup ON COMMIT DROP AS
SELECT id AS dup_id,
       min(id) OVER (PARTITION BY project_path) AS keep_id
FROM sessions.projects;

-- 2. Re-point sessions off duplicate project rows onto the surviving row.
UPDATE sessions.sessions s
SET project_id = d.keep_id
FROM proj_dedup d
WHERE s.project_id = d.dup_id AND d.dup_id <> d.keep_id;

-- 3. Re-point git_repos likewise (FK is NO ACTION -> must move before delete).
UPDATE sessions.git_repos r
SET project_id = d.keep_id
FROM proj_dedup d
WHERE r.project_id = d.dup_id AND d.dup_id <> d.keep_id;

-- 4. Delete the now-unreferenced duplicate rows.
DELETE FROM sessions.projects p
USING proj_dedup d
WHERE p.id = d.dup_id AND d.dup_id <> d.keep_id;

-- 5. Rebuild the unique index now that the column is truly unique.
REINDEX INDEX sessions.projects_project_path_key;

-- ---- DRY-RUN OUTPUT ----
\echo '--- projects after dedup (rows should now equal distinct paths) ---'
SELECT count(*) AS projects_after, count(DISTINCT project_path) AS distinct_paths
FROM sessions.projects;
\echo '--- any remaining duplicate paths? (expect 0 rows) ---'
SELECT project_path, count(*) FROM sessions.projects GROUP BY project_path HAVING count(*) > 1;

ROLLBACK;
-- COMMIT;
