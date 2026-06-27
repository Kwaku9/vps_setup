#!/usr/bin/env bash
set -euo pipefail
MODELS=/opt/podman-data/nomic-embed/models
GGUF=nomic-embed-text-v1.5.Q8_0.gguf
URL=https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/$GGUF

mkdir -p "$MODELS"
if [ ! -f "$MODELS/$GGUF" ]; then
  echo "Downloading $GGUF ..."
  curl -fL -o "$MODELS/$GGUF" "$URL"
fi

podman rm -f nomic-embed 2>/dev/null || true
podman run -d --name nomic-embed --network enterprise_network --memory 2g \
  -v "$MODELS":/models:Z \
  ghcr.io/ggml-org/llama.cpp:server \
  --model /models/$GGUF \
  --embeddings --pooling mean --parallel 1 \
  --ctx-size 8192 --ubatch-size 8192 \
  --host 0.0.0.0 --port 8090
echo "nomic-embed started on enterprise_network at nomic-embed:8090"
