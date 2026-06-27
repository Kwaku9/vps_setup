# Local-GPU Embedding ↔ VPS Sync — Parity Checklist & Accounting

**Purpose:** run the heavy embedding pass on the Fedora GPU (RTX 3050, 6 GB) instead of the
VPS CPU (~12 h → ~minutes), then sync the vectors back up to the VPS where search/eval run.
This only works if the local sessions data is an **exact mirror** of the VPS. This doc is the
go/no-go accounting before any local work starts.

**Status of this doc:** VPS side fully inventoried (verified 2026-06-27). Local side = a
checklist for you to verify. Two open decisions at the bottom.

---

## 1. The architecture (and why it's sound)

Embeddings are deterministic, portable data: `same model + same text → identical 768 numbers`,
regardless of which machine computes them. So we split the work by cost:

```
FEDORA (RTX 3050)                                  VPS (source of truth)
─────────────────                                  ─────────────────────
                          (A) pg_dump sessions  ◄── sessions schema (816 MB)
local Postgres mirror ◄───────── DOWN ───────────
   │
   │ (B) embed on GPU (same models, same code)
   ▼
local spike.emb_* vectors ──── (C) pg_dump UP ───► VPS spike.emb_* vectors
                                                     │
                                   (D) gold set + run_eval run HERE
                                       (query-side embedding = VPS's own
                                        EmbeddingGemma/nomic; pgvector does
                                        the distance math — no GPU needed)
```

- **Sessions flow DOWN** (VPS → local), once, to mirror.
- **Vectors flow UP** (local → VPS), once, after embedding.
- Everything after that (gold set, scoreboard) runs on the VPS.

---

## 2. The parity invariant — what MUST be identical

The synced-up vectors are keyed by `session_uuid` (and `message_id`). For them to line up with
the VPS's keyword corpus + gold set, the local mirror must satisfy:

| Must match exactly | Why | Strictly required? |
|---|---|---|
| **`session_uuid` set + per-session content** | search ranks by `session_uuid`; the vector must represent the same text | **YES — hard requirement** |
| **`content_text` per message** (incl. ingest sanitisation: null bytes stripped) | the vector encodes this exact text | **YES** |
| `message_id` values (`integer`/serial) | PK of the gemma embedding rows | **No** — search groups by `session_uuid`, never joins on `message_id`. But `pg_dump`-down gives it for free. |
| **Embedding model artifact** (see §4) | doc vectors (local) and query vectors (VPS) must share one "meaning map" | **YES** |
| **Prefixes + chunking** (`text_prep`, `datasets.max_chars=6000`) | changes the text that gets embedded | **YES — use the same committed code locally** |

> **The safe path:** mirror by `pg_dump` of the VPS `sessions` schema **DOWN** (§5), NOT by
> re-ingesting JSONL locally. A local re-ingest would produce different `message_id`s and risks
> content/sanitisation drift. `pg_dump`-down guarantees byte-exact parity of everything.

---

## 3. VPS source-of-truth inventory (verified 2026-06-27)

| Component | Value |
|---|---|
| Postgres | **16.14** (Debian build) |
| pgvector | **0.8.2** |
| DB / schema | `enterprise` / `sessions` |
| `sessions` schema total size | **816 MB** |
| `sessions.messages` | **263,308 rows**, 758 MB · `id` = `integer` (serial) |
| `sessions.sessions` | **692 rows**, 704 kB · `session_uuid` = `text` |
| other tables | artifacts 6,738 · tool_calls 56,032 · git_commits 557 · subagents 637 · projects 35 · session_events 186 · git_repos 8 |
| newest session `started_at` | **2026-06-27 21:11 UTC** (data is live — see drift risk) |

**Embedding model artifacts (must be reproduced identically on local GPU):**

| Model | File | Size | Source |
|---|---|---|---|
| EmbeddingGemma-300M | `embeddinggemma-300M-Q8_0.gguf` | 318 MB | `huggingface.co/ggml-org/embeddinggemma-300M-GGUF` |
| nomic-embed-text-v1.5 | `nomic-embed-text-v1.5.Q8_0.gguf` | 139 MB | `huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF` |

**Current `spike` schema state on VPS (what's already done):**

| Object | Rows | Note |
|---|---|---|
| `kw_useronly` / `kw_userasst` | 667 / 667 | keyword corpus **fully populated** (stays on VPS; not re-done locally) |
| `emb_gemma_useronly` | 20 | smoke only — **delete before real pass** |
| `emb_nomic_userasst` | 3 | smoke only — **delete before real pass** |
| `emb_gemma_userasst`, `emb_nomic_useronly` | 0 | empty |
| `eval_queries` | 0 | gold set not built yet |

(Note: kw shows 667 vs 692 sessions — ~25 sessions have no qualifying user/assistant text and are
legitimately absent from the keyword corpus. Expected, not a defect.)

---

## 4. Embedding-model consistency (the subtle one)

The VPS embeds **queries** at search time with the **Q8_0 GGUF** models via llama.cpp. For doc
vectors and query vectors to share one map, the local **doc** embedding should use the **same
artifact**.

- ✅ **Recommended:** run the **same two GGUF files** on the local GPU via **llama.cpp compiled
  with CUDA** (`--n-gpu-layers 99`). Numerically identical to the VPS; reuses the exact same
  serving path; the 3050's 6 GB holds both Q8 GGUFs with room to spare. Then point
  `embed_sessions.py` at the local GPU endpoints (`NOMIC_BASE_URL` / `LITELLM_BASE_URL` envs).
- ⚠️ **Alternative (HF fp16 + sentence-transformers on CUDA):** faster to set up, but fp16 ≠ Q8,
  so doc (local fp16) and query (VPS Q8) vectors differ slightly. Usually negligible for cosine,
  but it is **not** "exact." Only choose this if you also switch the VPS query side to the same
  HF model — not worth it for this spike.
- **nomic context:** keep local nomic at **2048** (its GGUF `n_ctx_train`) to match the VPS, and
  keep the prefixes (`search_document:` / `search_query:`). Do **not** run local nomic at 8192 for
  this spike — it would put docs and queries on different maps. (8192 is a future enhancement,
  for when the VPS query side also runs 8192.)

---

## 5. The checklist

### Phase 0 — Freeze & account (VPS)
- [ ] **Decide the snapshot moment.** The `sessions` data grows daily (3 AM `daily-session-ingest`
  cron, newest session 2026-06-27 21:11). Pick a freeze point.
- [ ] **Prevent drift during the run.** Either (a) pause the 3 AM cron until the spike is done, or
  (b) accept that sessions added after the snapshot won't have vectors — and build the gold set
  ONLY from snapshot sessions. (Recommended: pause the cron; it's one crontab line.)
- [ ] **Clear the smoke embeddings** so the real pass starts clean:
  `DROP`/`TRUNCATE spike.emb_gemma_useronly, spike.emb_nomic_userasst` (or `TRUNCATE` all 4 emb tables).

### Phase 1 — Sync the DB DOWN (VPS → local)
- [ ] `pg_dump` the `sessions` schema from the VPS:
  `podman exec postgres pg_dump -U postgres -d enterprise -n sessions -Fc -f /tmp/sessions.dump`
  (custom format; ~816 MB raw, compresses to a few hundred MB).
- [ ] Transfer to Fedora over the **tailnet** (the vps↔Fedora tailscale link already exists).
- [ ] Record the VPS parity fingerprint (run the §6 query on the VPS, save output).

### Phase 2 — Local Postgres + pgvector
- [ ] Local Postgres **16.x** running (match the VPS major; avoids restore quirks).
- [ ] `pgvector` installed locally (any ≥0.5 supports `vector(768)`; 0.8.x matches the VPS).
  `CREATE EXTENSION vector;` must succeed BEFORE restoring vector columns.
- [ ] Restore: `pg_restore -d <localdb> /path/sessions.dump` (creates `sessions` schema).
- [ ] Create the `spike` schema locally too: apply `tools/spikes/session-recall/schema.sql`.
- [ ] **Verify parity** — run §6 on local; output MUST match the VPS fingerprint line-for-line. Stop if not.

### Phase 3 — Local GPU embedding stack
- [ ] NVIDIA driver + container GPU access on Fedora (e.g. `nvidia-container-toolkit`), `nvidia-smi` works.
- [ ] Download the SAME two GGUFs (§3 source URLs) to the local box.
- [ ] Run llama.cpp **CUDA** server for each (same flags as `nomic-up.sh`, plus `--n-gpu-layers 99`),
  OR set up the HF-fp16 path per §4 (not recommended).
- [ ] Get the spike code locally: clone this repo (or copy `tools/spikes/session-recall/`), build the
  `spike-tools` image, and write a local `spike.env` pointing `PGHOST`→local DB,
  `LITELLM_BASE_URL`/`NOMIC_BASE_URL`→the local GPU endpoints.

### Phase 4 — Embed locally on the GPU
- [ ] Run the real pass (no `--limit`) for all four cells:
  `for ds in useronly userasst; do ./run.sh embed_sessions.py --model gemma --dataset $ds; ./run.sh embed_sessions.py --model nomic --dataset $ds; done`
- [ ] Sanity-check local counts (gemma ≈ 11,711 + 44,276 docs across cells; nomic ≈ 692 × 2).

### Phase 5 — Sync the vectors UP (local → VPS)
- [ ] `pg_dump` only the embedding tables locally:
  `pg_dump -d <localdb> -t spike.emb_gemma_useronly -t spike.emb_gemma_userasst -t spike.emb_nomic_useronly -t spike.emb_nomic_userasst -Fc -f spike-emb.dump`
- [ ] Transfer to VPS over tailnet.
- [ ] Restore into the VPS `spike` schema (the emb tables already exist and are empty/smoke-cleared):
  `podman exec -i postgres pg_restore -U postgres -d enterprise --data-only -t emb_... < spike-emb.dump`
  (data-only, since the tables/DDL already exist on the VPS).
- [ ] Verify counts on the VPS match the local counts.

### Phase 6 — Gold set + eval (VPS)
- [ ] Build the gold set on the VPS — interactive, your part: `gen_queries.py` (approve/reject) and/or
  `add_query.py`. Sample only from snapshot sessions (Phase 0).
- [ ] `run_eval.py` → read the per-source scoreboard.

---

## 6. Parity verification query (run on BOTH, compare line-for-line)

Robust to `message_id` differences (orders by `session_uuid, sequence_num`, not `id`):

```sql
SELECT 'sessions_count'       AS k, count(*)::text AS v FROM sessions.sessions
UNION ALL SELECT 'messages_count', count(*)::text FROM sessions.messages
UNION ALL SELECT 'session_uuid_set',
  md5(string_agg(session_uuid, ',' ORDER BY session_uuid)) FROM sessions.sessions
UNION ALL SELECT 'message_content_hash',
  md5(string_agg(md5(s.session_uuid||':'||m.sequence_num||':'||coalesce(m.content_text,'')),
                 ',' ORDER BY s.session_uuid, m.sequence_num))
  FROM sessions.messages m JOIN sessions.sessions s ON s.id = m.session_id;
```

All four lines identical on local and VPS ⇒ **exact content parity**. Any mismatch ⇒ do not proceed.

---

## 7. Blockers & parity risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | **Live drift** — 3 AM ingest keeps adding sessions | local snapshot ≠ VPS by eval time; gold-set query for a post-snapshot session has no vector | **Pause the cron** during the spike; build the gold set only from snapshot sessions; re-snapshot if you want newer data |
| 2 | **Local mirror is a re-ingest, not a dump** | different `message_id`s (works for search) but risks content/sanitisation drift → wrong/unequal vectors | **Mirror via `pg_dump`-down (§5), not re-ingest.** If a local DB already exists, overwrite it or pass §6 parity check first |
| 3 | **Model artifact mismatch** (local fp16 vs VPS Q8) | doc & query vectors on slightly different maps → degraded recall | Run the **same Q8 GGUFs** on local GPU via llama.cpp-CUDA (§4) |
| 4 | **nomic context mismatch** (local 8192 vs VPS 2048) | doc/query map mismatch | Keep local nomic at **2048** + same prefixes |
| 5 | **Code drift** (different prefixes/chunking locally) | different text embedded | Use the **committed** `text_prep.py` / `datasets.py` (max_chars=6000) locally — same repo |
| 6 | **pgvector missing/old locally** | restore of `vector(768)` fails | Install pgvector (≥0.5; 0.8.x to match) and `CREATE EXTENSION vector` before restore |
| 7 | **Postgres major mismatch** | `pg_restore` quirks | Use Postgres 16.x locally |
| 8 | **Smoke rows left in place** | 20 gemma + 3 nomic stale rows pollute the synced set | TRUNCATE the 4 emb tables before the real pass (Phase 0) |
| 9 | **Disk** | local DB ~1 GB + vectors; transfers | Ensure ~3 GB free on Fedora; vectors-up dump ≈ a few hundred MB |

---

## 8. Open decisions (need your input to finalize)

1. **What is the local mirror today?** (a) a local Postgres with the `sessions` schema, (b) only the
   raw Claude Code JSONL files, or (c) nothing yet. → Determines whether we `pg_dump`-down fresh
   (recommended regardless) or validate an existing copy with §6.
2. **Local embedding stack:** llama.cpp-CUDA with the **same GGUFs** (recommended, exact parity) vs
   HF fp16 sentence-transformers (faster setup, slight numeric drift). → §4.

Once those are answered, the remaining setup (local llama.cpp-CUDA endpoints + the down/up sync
commands) is mechanical and I can script it.
