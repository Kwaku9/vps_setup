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
