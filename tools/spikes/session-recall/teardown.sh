#!/usr/bin/env bash
set -euo pipefail
podman rm -f nomic-embed 2>/dev/null || true
podman exec -i postgres psql -U postgres -d enterprise \
  -c "DROP SCHEMA IF EXISTS spike CASCADE;"
podman rmi localhost/spike-tools:latest 2>/dev/null || true
echo "spike torn down. Model GGUF left at /opt/podman-data/nomic-embed/ "
echo "(rm -rf that dir to reclaim ~150 MB of disk)."
