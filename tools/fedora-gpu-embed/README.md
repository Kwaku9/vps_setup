# Fedora GPU recall-freshness trigger

On-demand embedding of the session-recall delta on the **Fedora laptop GPU**
(RTX 3050), writing vectors to the VPS `recall.chunks`. Use when you want recall
brought current faster than the VPS-CPU nightly cron (e.g. a large backlog), or
just on demand.

## Why GPU-side
The bulk/heavy embedding is ~2 orders of magnitude faster on the GPU than the
VPS CPU. Parity is exact: the laptop runs the **same `embeddinggemma-300M-Q8_0.gguf`**
via llama.cpp (CUDA) that the VPS query side uses (CPU) — measured cosine 0.9997
on identical input, so GPU-embedded vectors share the same map as the existing
corpus and the query side.

## Architecture
```
Fedora (GPU)                                  VPS (postgres, loopback-only)
  llama.cpp :18090 (CUDA, embeddinggemma)        recall.chunks
  embed_recall_delta.py ── ssh -L tunnel ──► 127.0.0.1:5432 (read delta / write vectors)
```
The VPS postgres is published only on `127.0.0.1`, so the script runs **on
Fedora** and reaches the DB through an SSH tunnel. The GPU does the embedding;
vectors land in the VPS DB.

## One-time setup on Fedora (already in place as of 2026-06-30)
- podman + NVIDIA CDI (`/etc/cdi/nvidia.yaml`), `nvidia-smi` works.
- `~/spike-models/embeddinggemma-300M-Q8_0.gguf` (same HF GGUF as the VPS).
- image `ghcr.io/ggml-org/llama.cpp:server-cuda`.
- system `python3` + `psycopg2` + `requests`.
- Fedora can SSH to the VPS (`root@<vps-tailnet>`) for the tunnel + secret fetch.

## Usage (on Fedora)
```sh
cd ~/recall-gpu          # holds embed-recall-now.sh + embed_recall_delta.py
./embed-recall-now.sh           # embed the delta; GPU server left running
./embed-recall-now.sh --stop    # also stop the GPU server when done
```
The script: starts the local llama.cpp CUDA server (parity-exact flags) if not
already up → opens the SSH tunnel → fetches the `session_ingest` DB password from
the VPS vault (into env, never written to disk) → runs `embed_recall_delta.py`
pointed at the local GPU and the tunneled DB → tears the tunnel down.

`embed_recall_delta.py` is the same idempotent script the VPS nightly cron uses
(`NOT EXISTS` + `ON CONFLICT DO NOTHING`); only the embedding endpoint differs
(local GPU vs VPS CPU). Safe to re-run.

## Embedding prefix, fail-loud over-length, VPS fallback (2026-10)
- `embed_owui_kb.py` now applies the Open WebUI document prefix
  (`RAG_EMBEDDING_CONTENT_PREFIX`, default `title: none | text: `), matching the
  open-webui env in `roles/ai-stack/tasks/main.yml`. Queries get
  `task: search result | query: ` from OWUI itself. KB vectors embedded RAW before
  this change are in a different space from prefixed queries: re-run
  `reindex-owui-kb-now.sh` (full, not `--only-stale`) after deploying. NOT yet done.
- All three embed scripts no longer truncate over-length input. The row is logged,
  skipped, counted, and the run exits nonzero. Skipped rows are retried next run.
- Offline test: `python3 test_embed_prefix.py` (stubbed endpoint; includes controls
  that must fail, e.g. `RAG_EMBEDDING_CONTENT_PREFIX="" python3 test_embed_prefix.py`
  exits nonzero). It also parses `main.yml` so the default prefix cannot drift.
- VPS CPU fallback `ubatch_size` raised 512 -> 2048 (all.yml shadows role defaults,
  both changed). llama.cpp embeddings need the whole input in one ubatch, so
  480-640 token chunks plus prefix failed at 512. Expected RSS: roughly +0.5 to +0.9 GB
  versus the 512 setting (2048 was observed at ~1.2 GB RSS for a 318 MB model; the
  compute buffer scales with ubatch). Container cap stays `memory: 2g`. The VPS
  has run swap-exhausted with 276 MB minimum available (alpine-vps-memory-pressure),
  so this is RISKY: deploy only after checking `free -m`; never `podman system prune`.
