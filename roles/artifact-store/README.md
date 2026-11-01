# artifact-store role: vertical slice plan

Status: DRAFT, 2026-10-12. REVISED 2026-10-15: bytes live in Cloudflare R2 (primary); RustFS is deferred (see Durability). Nothing built. Patterns copied from the session ETL
(vps_setup/tools/ingest-sessions.py, fedora-gpu-embed, session-recall-mcp),
Mail Kit (nucybertech-site/mailkit/mcp) and Try the Look (la-rouge-brows/mcp/try-the-look).

## Goal

Every AI-generated artifact lands in one place the user owns, is searchable by
meaning from any agent, and is durable. Replaces: Downloads folder, provider-hosted
artifacts, manual copying between sessions.

## Assumptions (change these and the plan changes)

1. Main reader is agents. OnlyOffice is out of v1; add it later as an editor over presigned URLs.
2. Index lives in the existing `enterprise` Postgres, new `artifacts` schema, own roles. Isolated from `sessions.*` and `recall.*`.
3. v1 is text-first (md, html, txt, pdf, docx, code, json). Binaries are stored and indexed by metadata plus extracted text or caption only. No audio or video embedding.
4. MCP servers and the index run on the VPS pod pattern. The BYTES live in Cloudflare R2, not on the VPS disk (the daily backup needs 12 GiB free and has been aborting). No Lambda, no Aurora, no claude.ai connector in v1.
5. Rules that apply throughout: loopback or tailnet binds only (never 0.0.0.0 on the host), secrets in the VPS ansible vault, every check paired with a control that must fail, no deletion on inference (quarantine instead).

## Architecture

```
agent (Claude Code, Codex)
   |  stdio MCP: save_artifact / search_artifacts / get_artifact
   v
artifact-mcp (python, FastMCP, in a podman container, via ssh podman exec -i)
   |-- Cloudflare R2 bucket `aicortex-artifacts` (S3 API, presigned URLs)   bytes, key = artifacts/YYYY/MM/<sha256[:16]>-<slug>.<ext>
   |-- Postgres enterprise.artifacts.*        objects + chunks(vector(768), HNSW)
   |-- LiteLLM alias `embeddinggemma`         query-time embeddings (existing, laptop GPU then VPS CPU)
laptop timer: extract text -> chunk (2000 chars) -> embed on laptop GPU -> insert via tunnel (same as embed_recall_delta.py)
Neo4j (VPS): (:Artifact)-[:CREATED_IN]->(:Session), (:Artifact)-[:IN_PROJECT]->(:Project)
```

## Schema (draft)

```sql
CREATE SCHEMA artifacts;
CREATE TABLE artifacts.objects (
  id           bigserial PRIMARY KEY,
  sha256       text NOT NULL UNIQUE,          -- dedup key, also the idempotency key
  s3_key       text NOT NULL,
  title        text,
  ext          text,
  mime         text,
  size_bytes   bigint,
  source       text,                          -- claude-code | codex | claude-ai | higgsfield | downloads-backfill
  session_uuid text,                          -- joins to sessions.sessions when known
  project      text,
  tags         text[] DEFAULT '{}',
  status       text NOT NULL DEFAULT 'reserved',-- reserved | stored | extracted | embedded | quarantined
  created_at   timestamptz DEFAULT now()
);
CREATE TABLE artifacts.chunks (
  object_id  bigint REFERENCES artifacts.objects(id),
  chunk_idx  int,
  snippet    text,
  embedding  vector(768),
  PRIMARY KEY (object_id, chunk_idx)
);
CREATE INDEX ON artifacts.chunks USING hnsw (embedding vector_cosine_ops);
-- roles: artifact_ro (SELECT), artifact_ingest (SELECT, INSERT, UPDATE status)
```

Rules carried over from the ETL: never GROUP BY / DISTINCT / join on the vector column;
delta selection uses `NOT EXISTS`; insert uses `ON CONFLICT DO NOTHING`; whitespace check
uses `~ '[^[:space:]]'`, not trim.

## Tool signatures (one tool list, shared by stdio and any later HTTP transport)

- `save_artifact(sha256, size, ext, title, project?, tags?, session_uuid?)` -> `{id, deduped, put_url?}`
  The server runs on the VPS and the file is on the laptop, so the CALLER hashes the file in its shell and uploads
  the bytes itself with the returned presigned PUT URL; bytes never go through model context. A `text` argument is
  allowed for small notes. Server verifies size + sha256 on confirm; mismatch quarantines the row. Idempotent on sha256. Credential scrubber runs on extracted text before indexing.
- `search_artifacts(query, k=8, project?, since?, tags?)` -> ranked list, deduped per object, with snippet and id.
- `get_artifact(id, max_chars=8000)` -> extracted text, plus a presigned GET URL for the original (short expiry, served via our own route if a client mangles query strings).
- Read and write are two separate servers with two credentials, as in Mail Kit.
  Retrieved text is labelled untrusted in the tool description.

## Slice steps

Each step has a check and a control that must fail.

1. **R2 bucket + scoped tokens.** Create bucket `aicortex-artifacts` (a SEPARATE bucket from `aicortexbak`). Two Cloudflare API tokens, both scoped to this bucket only: a writer (Object Read & Write) used by the write server to mint presigned PUT URLs, and a reader (Object Read) used by the read server and the rclone mount. The user creates them in the Cloudflare dashboard and places them in the VPS vault; this role renders 0600 env files with no_log.
   Check: presigned PUT then GET round trip, sha256 matches. Controls that must fail: an expired presigned URL is refused; the reader token cannot PUT; the artifacts tokens cannot list `aicortexbak`.
2. **Schema + roles.** Migration in vps_setup, grants as above.
   Check: `artifact_ro` can SELECT. Control: `artifact_ro` INSERT fails.
3. **save_artifact.** Hash, dedup, PUT, row insert, status=stored.
   Check: save the same file twice, one object, `deduped=true`. Control: save a file with a different byte, new row.
4. **Extract + embed job.** Laptop timer modelled on `embed-recall.timer`: extract text (md/txt/html/pdf/docx), chunk, embed on laptop GPU, insert via tunnel. Reuse `embeddinggemma` prefixes.
   Check: 20 known artifacts reach status=embedded. Control: whitespace-only file stays at `extracted`, delta reaches 0 (no infinite re-selection).
5. **search_artifacts / get_artifact.** Read-only role, stdio over `ssh podman exec -i`.
   Check: a query phrased differently from the source text returns it in top 3 for at least 8 of 10 hand-written probes. Control: nonsense query returns low-similarity results, not a confident hit; unrelated project filter returns none.
6. **Backfill Downloads.** Dry run first, report only. Copy to bucket by hash, then quarantine originals into a dated folder; no deletion.
   Check: count of files in == count of objects + deduped. Control: a deliberately corrupted copy fails hash verification.
7. **Restore drill.** Rebuild a scratch bucket and scratch schema from the second copy and the pg_dump.
   Check: object count and 5 random sha256s match. Control: tamper one object in the second copy and confirm the drill catches it.
8. **Freshness alert.** VPS cron modelled on `recall-freshness-check.sh.j2`: alert if newest `stored` object is more than 24h older than newest `embedded`, or if the replica is stale.
   Check: alert fires on a staged stale state. Control: no alert on a healthy state.

## Durability

R2 is a single provider and a single account. What it must be protected from: account loss, an accidental delete, a bad token.

- Keys are content-addressed, so an object is never overwritten. Overwrite protection is structural (R2 has no object versioning as far as I know; confirm before relying on it).
- Separate bucket and tokens from the VPS backup, so neither credential can touch the other's data.
- The application never issues a delete. Removing something is a quarantine-prefix move plus an operator action.
- Second copy: the laptop pulls nightly with `rclone copy` (copy, not sync, so a deletion never propagates) to the external drive, or to laptop disk until the drive exists. Modeled on `vps-backup-pull.sh`: hash-verify, fail loud, never trust an unverified copy. Open: external drive only, or also a second provider (GCS is already used for the session archive).
- `pg_dump` of the `artifacts` schema goes to `aicortex-artifacts/_db/` and to the second copy.
- No client-side encryption on the primary: presigned URLs need plaintext objects, and R2 encrypts at rest server-side. If client-side encryption matters later, put an rclone crypt overlay on the SECOND copy only (names off, contents on, passphrase in the vault plus one offline copy).
- Existing VPS backup note: it is NOT healthy. The last daily tar landed in R2 on 2026-10-06 and runs have aborted on low disk since (see memory vps-no-offsite-backup).

## Browsing: rclone mount (convenience only)

A read-only FUSE view of the bucket so objects can be browsed in a file manager or opened by tools that expect paths.
It is never a service dependency and nothing in the pipeline reads through it.

- Mount `r2:aicortex-artifacts` directly on the laptop with the READER token, so a mistake cannot write. Live, not stale.
- Flags: `--read-only --vfs-cache-mode full --vfs-cache-max-size 5G --cache-dir ~/.cache/rclone-artifacts --dir-cache-time 5m`. The cache counts against laptop disk, so keep the cap small.
- systemd user unit with `Restart=on-failure`, not in any boot dependency chain. If the network drops the mount goes stale and nothing else is affected.
- Do NOT mount read-write: writes would bypass hashing, dedupe, the row insert and the embed trigger.
- Do NOT point a quadlet, Postgres or an indexer at it.

## Decks: backup and retrieval (added 2026-10-15)

Decks are the slide-deck skill's reveal.js output. Measured 2026-10-15: `/opt/compose/decks` on the VPS is 513 MB, they are DATA
(pushed by scp, in no repo), and laptop sources sit in `vps_setup/local/decks` (43 MB, gitignored) and `aicortex-marketplace/brand/decks`
(42 MB). The VPS daily backup that would cover them has been aborting, so today a lost disk means lost decks.

- Unlike artifacts, decks are NOT content-addressed: a deck is an HTML file with relative links to `vo-<deck>/` and `bg/` audio.
  Keep the directory layout intact under their own prefixes in the same bucket: `decks/live/` (mirror of the host) and
  `decks/src/` (laptop authoring folders).
- Backup: nightly cron on the VPS, `rclone copy /opt/compose/decks r2:aicortex-artifacts/decks/live --backup-dir
  r2:aicortex-artifacts/decks/_replaced/<date> --exclude '*.bak*'`. Copy, never sync. From the laptop, the same for sources to `decks/src/`.
- Retrieve: `rclone copy r2:aicortex-artifacts/decks/live/<deck>* <host dir>`; nginx serves static files, no restart.
  Include the matching `vo-<deck>/` and `bg/` or narration returns 404 (see memory buildfolio-self-hosted-decks).
- Narration markdown (`*-narration.md`) is also saved through `save_artifact`, so what a deck says is searchable.
- Verify: restore one deck into a scratch directory and load it. Control: delete its `vo-` folder from the restore and confirm the
  check notices the missing audio.
- Needs the writer token on the VPS (already planned). It does not need a new bucket.

## Viewing this plan over Tailscale (temporary)

`architecture.html` is served tailnet-only (not Funnel) by `tailscale serve` on the laptop at
`https://<laptop_tailnet_host>:8446/` (host: `laptop_tailnet_host` in the encrypted all.yml), from a directory that holds only that one page, not this whole role.
It works only while the laptop is awake. Remove with `tailscale serve --https=8446 off`.

## Out of scope for v1

Self-hosted RustFS (the role keeps its tasks, disabled, until the VPS has disk to spare or the bytes move off R2),
OnlyOffice, claude.ai connector (needs real domain + OAuth, and bytes cannot pass through it),
Higgsfield/claude.ai pull jobs, audio/video embedding, Aurora, Lambda, summaries.

## Risks to watch

- Single provider: R2 account or token loss. The second copy and the restore drill (step 7) exist for this. R2 presign/multipart behavior differs slightly from AWS; test large uploads.
- Laptop GPU is shared and the embedder grows about 1 GB per day; keep embedding text-only and batch-sized like the recall job.
- `vps_setup` is public and `local/` is gitignored: no secrets or hostnames in tracked files.
- Upstream sources are uncommitted (Mail Kit source as of 2026-09-23, whitespace fix in the embed delta). Commit or copy deliberately before building on them.
- Credentials in artifact text: scrub before indexing, because the index is searchable and replicated.

## Open questions

1. Agents vs. user as main reader (assumption 1 above).
2. Shared vs. isolated database (assumption 2).
3. Expected volume including audio and video.
4. (DECIDED 2026-10-15) Primary bytes in Cloudflare R2, mounted read-only with rclone. Open: second-copy target (external drive only, or also GCS).
5. (DECIDED 2026-10-12) Lives in vps_setup as `roles/artifact-store/`; tooling (extractor, embed job, MCP server) goes under `tools/` and `roles/artifact-store/files/`, following `session-recall-mcp` and `fedora-gpu-embed`. Not yet wired into site.yml.
