#!/bin/sh
# embed-recall-now.sh — ON-DEMAND recall freshness, GPU-side.
#
# Runs ON the Fedora laptop. Brings up the local llama.cpp CUDA EmbeddingGemma
# server (parity-exact with the VPS), opens an SSH tunnel to the VPS postgres
# (which is loopback-only there), and runs embed_recall_delta.py so the heavy
# embedding happens on the GPU while vectors land in the VPS recall.chunks.
#
# Usage:  ./embed-recall-now.sh          (embed the delta; leave GPU server up)
#         ./embed-recall-now.sh --stop   (also stop the GPU server when done)
set -eu

VPS=root@100.121.252.38            # alpine-vps over tailnet
GPU_PORT=18090                     # 8080/8090 are taken by VS Code on Fedora
DB_TUNNEL_PORT=5433
MODELS="${MODELS:-/home/general/spike-models}"
GGUF=embeddinggemma-300M-Q8_0.gguf
IMG=ghcr.io/ggml-org/llama.cpp:server-cuda
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
STOP_SERVER=0; [ "${1:-}" = "--stop" ] && STOP_SERVER=1

TUNNEL_PID=""
cleanup() {
  [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null || true
  [ "$STOP_SERVER" = "1" ] && podman stop llama-embed-gpu >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# 1. Local GPU embedding server (parity-exact flags) — start only if not already up.
if ! curl -sf "http://127.0.0.1:$GPU_PORT/health" >/dev/null 2>&1; then
  echo "[gpu] starting llama.cpp CUDA EmbeddingGemma on :$GPU_PORT"
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

# 3. Fetch the session_ingest DB password from the VPS vault (into env, never printed).
PGPASSWORD=$(ssh "$VPS" "podman exec ansible-deployment sh -lc 'cd /ansible && ansible-vault view vault.yml 2>/dev/null'" \
              | sed -n 's/^pg_session_ingest_password:[[:space:]]*//p' | head -1 | tr -d "\"' ")
[ -n "$PGPASSWORD" ] || { echo "FATAL: could not fetch DB password from vault"; exit 1; }
export PGPASSWORD

# 4. Embed the delta on the LOCAL GPU; write vectors to the VPS recall.chunks.
export PGHOST=127.0.0.1 PGPORT="$DB_TUNNEL_PORT" PGDATABASE=enterprise PGUSER=session_ingest
export LITELLM_BASE="http://127.0.0.1:$GPU_PORT/v1" LITELLM_KEY="" GEMMA_MODEL=embeddinggemma
echo "[embed] running embed_recall_delta.py — GPU embeddings -> VPS recall.chunks"
python3 "$SCRIPT_DIR/embed_recall_delta.py"
echo "[done] recall.chunks is current. (GPU server left running; pass --stop to shut it down.)"
