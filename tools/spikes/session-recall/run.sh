#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
podman run --rm -it --network enterprise_network \
  --env-file "$HERE/spike.env" \
  -v "$HERE":/spike -w /spike \
  localhost/spike-tools:latest python "$@"
