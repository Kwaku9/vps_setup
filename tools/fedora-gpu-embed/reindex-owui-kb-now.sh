#!/bin/sh
# reindex-owui-kb-now.sh — re-embed OpenWebUI knowledge-base chunks on the Fedora GPU
# and sync the vectors up to the VPS openwebui.document_chunk (loopback-only postgres,
# reached via SSH tunnel). Companion to embed-recall-now.sh. Runs ON the Fedora laptop.
#
# Usage:  ./reindex-owui-kb-now.sh              (re-embed ALL KB chunks)
#         ./reindex-owui-kb-now.sh --only-stale (only rows not yet on embeddinggemma-768)
#         ./reindex-owui-kb-now.sh --stop       (also stop the GPU server when done)
set -eu

VPS=root@100.121.252.38            # alpine-vps over tailnet
GPU_PORT=18090                     # 8080/8090 are taken by VS Code on Fedora
DB_TUNNEL_PORT=5433
MODELS="${MODELS:-/home/general/spike-models}"
GGUF=embeddinggemma-300M-Q8_0.gguf
IMG=ghcr.io/ggml-org/llama.cpp:server-cuda
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ONLY_STALE=""; STOP_SERVER=0
for a in "$@"; do
  [ "$a" = "--only-stale" ] && ONLY_STALE="--only-stale"
  [ "$a" = "--stop" ] && STOP_SERVER=1
done

TUNNEL_PID=""
cleanup() {
  [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null || true
  [ "$STOP_SERVER" = "1" ] && podman stop llama-embed-gpu >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# 1. Local GPU embedding server. FULL GPU, no restrictions: the whole model is offloaded
#    (--n-gpu-layers 99) and the WHOLE GPU is handed to the container (nvidia.com/gpu=all).
#    Deliberately NO --parallel 1 / --threads 1 — those are the VPS CPU-neighbor throttles
#    and would cripple GPU throughput here. Start only if not already up (reused across runs).
if ! curl -sf "http://127.0.0.1:$GPU_PORT/health" >/dev/null 2>&1; then
  echo "[gpu] starting llama.cpp CUDA EmbeddingGemma on :$GPU_PORT (full GPU, unrestricted)"
  podman rm -f llama-embed-gpu >/dev/null 2>&1 || true
  podman run -d --name llama-embed-gpu --device nvidia.com/gpu=all \
    -v "$MODELS":/models:Z -p "127.0.0.1:$GPU_PORT:$GPU_PORT" "$IMG" \
    --model "/models/$GGUF" --embeddings --pooling mean \
    --ctx-size 2048 --ubatch-size 2048 --n-gpu-layers 99 \
    --host 0.0.0.0 --port "$GPU_PORT" >/dev/null
  i=0; until curl -sf "http://127.0.0.1:$GPU_PORT/health" >/dev/null 2>&1; do
    i=$((i+1)); [ "$i" -gt 40 ] && { echo "FATAL: GPU server did not become healthy"; exit 1; }; sleep 2
  done
fi
echo "[gpu] ready on :$GPU_PORT (VRAM: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null | head -1))"

# 2. SSH tunnel: Fedora:$DB_TUNNEL_PORT -> VPS 127.0.0.1:5432 (postgres).
ssh -fN -o ExitOnForwardFailure=yes -L "$DB_TUNNEL_PORT:127.0.0.1:5432" "$VPS"
TUNNEL_PID=$(pgrep -f "ssh -fN -o ExitOnForwardFailure=yes -L $DB_TUNNEL_PORT:127.0.0.1:5432 $VPS" | head -1)
echo "[tunnel] VPS postgres -> 127.0.0.1:$DB_TUNNEL_PORT"

# 3. Fetch the postgres password from the VPS vault (into env, never written to disk).
#    document_chunk lives in the openwebui schema; the postgres superuser owns it.
PGPASSWORD=$(ssh "$VPS" "podman exec ansible-deployment sh -lc 'cd /ansible && ansible-vault view vault.yml 2>/dev/null'" \
              | sed -n 's/^postgres_password:[[:space:]]*//p' | head -1 | tr -d "\"' ")
[ -n "$PGPASSWORD" ] || { echo "FATAL: could not fetch postgres password from vault"; exit 1; }
export PGPASSWORD

# 4. Re-embed on the LOCAL GPU; UPDATE vectors in the VPS openwebui.document_chunk in place.
export PGHOST=127.0.0.1 PGPORT="$DB_TUNNEL_PORT" PGDATABASE=enterprise PGUSER=postgres
export LITELLM_BASE="http://127.0.0.1:$GPU_PORT/v1" LITELLM_KEY="" GEMMA_MODEL=embeddinggemma VECTOR_LENGTH=1536
echo "[embed] running embed_owui_kb.py ${ONLY_STALE} — GPU embeddings -> VPS openwebui.document_chunk"
python3 "$SCRIPT_DIR/embed_owui_kb.py" ${ONLY_STALE}
echo "[done] OWUI KB vectors synced to embeddinggemma-768. (GPU server left running; pass --stop to shut it down.)"
