#!/bin/sh
# lint-zones.sh — keep network/zones.yml, network/flows.yml and the generated firewall
# snippets consistent.
#
#   1. unit tests for tools/netseg
#   2. zones.yml / flows.yml load and validate (addresses, pods, flows, enforce readiness)
#   3. roles/security/files/zone-*.rules equal a fresh render (no hand edits, no stale copy)
#
# Usage:  scripts/lint-zones.sh            check
#         scripts/lint-zones.sh --update   regenerate the rules files, then check
set -eu
cd "$(dirname "$0")/.."
export PYTHONPATH=tools
Z=network/zones.yml
F=network/flows.yml
OUT=roles/security/files

if [ "${1:-}" = "--update" ]; then
    python3 -m netseg.render --zones "$Z" --flows "$F" --out-dir "$OUT"
    echo "  zones: regenerated $OUT/zone-forward.rules and zone-input.rules"
fi

if ! out=$(python3 -m unittest discover -s tools/netseg/tests -t tools 2>&1); then
    echo "$out" | tail -25
    echo "  zones: unit tests FAILED" >&2
    exit 1
fi
python3 -m netseg.render --zones "$Z" --flows "$F" --out-dir "$OUT" --check
echo "  zones: OK — model valid, generated rules current"
