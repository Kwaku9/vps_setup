# Data-quality migrations & fixes

Repairs the shredded project identity caused by the `decode_project_path()` bug,
fixes a corrupt unique index, prunes empty session shells, and adds cross-machine
canonical identity in the graph projection.

> **Status — applied to prod `enterprise` DB on 2026-06-16 (in order 001→002→003).**
> By then the refactored ingest had already converged most data, so the run was
> largely idempotent: 001 found 0 duplicate paths (REINDEX still run); 002 pruned
> 1 remaining empty shell (0 commits detached); 003 deleted 1 orphan project row.
> Final state: **28 canonical projects, 617 sessions, 0 empty shells, 0 mangled,
> 0 sessions without a cwd link.** Verified stable across a subsequent full ingest
> cycle (projects held at 28, no regression). Files are kept `ROLLBACK`-by-default
> for safe re-runs; they were applied by flipping the trailing `ROLLBACK;`→`COMMIT;`.

These files are **repo copies of deployed-only assets** (the canonical `ingest`
and `sessions-graph` files live on the VPS under `/opt/compose/...`, untracked in
git). `deploy-data-quality-fixes.sh` pushes them, backing up each target.

## What's here

| File | Part | What it does |
|------|------|--------------|
| `../session-ingestion/ingest-sessions.py` | **A** | `decode_project_path` becomes a documented lossy *fallback*; the project is resolved per session from the record `cwd` (authoritative). |
| `001_repair_project_path_unique_index.sql` | fix | Dedup byte-identical `project_path` rows (corrupt index — glibc/collation), then `REINDEX`. **Must run first.** |
| `002_prune_empty_session_shells.sql` | item 3 | Delete the 14 zero-message Session shells (their 18 git commits `SET NULL` and re-correlate next git ingest). |
| `003_backfill_canonical_project_paths.sql` | **A** | Rebuild canonical Project rows from `messages.cwd`, re-point sessions + git_repos, delete mangled rows. |
| `../sessions-graph/load-full.cypher` | **C** | Adds the `:Codebase` layer (cross-machine identity, keyed on repo/leaf name). |
| `../local/etl/sync_sessions_to_neo4j.py` | **C** | Same `:Codebase` layer in the local projection (`create_codebase_layer`). |

> **Strict order:** `001 → 002 → 003`, then **C**. 003's `ON CONFLICT`/path-joins
> need 001's healthy index; C's leaf-name keys need 003's canonical paths.

All migrations are **transactional and end in `ROLLBACK`** (dry-run). Each is
sequential-commit-dependent: dry-run shows useful output only once the *previous*
migration is committed.

## Apply order

1. **Deploy code** (backs up every target on the VPS, no DB change yet):
   ```bash
   ./deploy-data-quality-fixes.sh --files
   ```

2. **Apply the migrations IN ORDER.** For each of `001`, `002`, `003`:
   ```bash
   # dry-run (ROLLBACK) — review output
   ssh root@alpine-vps "podman exec -i postgres sh -c 'PGPASSWORD=\$POSTGRES_PASSWORD psql -U postgres -d enterprise'" \
     < migrations/00N_*.sql
   # then commit: edit the file, change trailing `ROLLBACK;` -> `COMMIT;`, re-run
   ```
   - `001` expected: rows == distinct paths (no duplicate `project_path`), index rebuilt.
   - `002` expected: 0 empty shells remain; ~18 commits unlinked (re-correlate later).
   - `003` expected: ~27 clean Project rows, no `-home-...` / `.../vps/setup`.

   `./deploy-data-quality-fixes.sh` (no args) does the file push **and** dry-runs
   `001` for you; apply `002`/`003` manually after committing `001`.

3. **Resync both graph projections** so corrected paths + `:Codebase` materialize:
   ```bash
   ssh root@alpine-vps 'STAGE=/opt/compose/sessions-graph/csv /opt/compose/sessions-graph/sync.sh'   # VPS
   # local: run local/etl/sync_sessions_to_neo4j.py over your PG tunnel
   ```

## Rollback

- **Code**: each deploy leaves `<file>.bak-<timestamp>` on the VPS; copy it back.
- **Migrations**: transactional. Before COMMIT there is nothing to undo. After
  COMMIT, restore from the nightly `vps-backup` (cron `0 2 * * *`) if needed.

## Caveats / follow-ups

- **Broader index corruption** (001): a glibc/collation change corrupts *every*
  collation-sensitive text index, not just `project_path`. After committing 001,
  schedule a full `REINDEX DATABASE enterprise;` in a maintenance window
  (`amcheck` can confirm which indexes are affected).
- **Leaf-name collisions** (C): two different repos sharing a leaf dir name would
  merge into one `:Codebase`. Workspace names look unique today; add a guard
  (require a matching `repo_name`) if that changes.
- **`git_repos` is VPS-only/thin**: `repo_path_local`/`project_id` are unpopulated,
  so it's used only to *enrich* `:Codebase`, not as the key. Backfilling it (and a
  real git remote URL) is a worthwhile follow-up.
