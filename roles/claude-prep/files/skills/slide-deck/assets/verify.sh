#!/usr/bin/env bash
# verify.sh — serve a deck on a free port for Playwright verification.
# Playwright blocks file:// URLs, so the deck must be served over http.
#
#   bash verify.sh <deck.html>
#
# Prints the URL and the server PID. Kill the server BY PID when done
# (kill <pid>) — do NOT `pkill -f` the port/pattern: when run via an inline
# shell the pattern matches the agent's own command line and self-kills it.
set -euo pipefail
DECK="${1:?usage: verify.sh <deck.html>}"
[ -f "$DECK" ] || { echo "no such file: $DECK" >&2; exit 1; }
DIR="$(cd "$(dirname "$DECK")" && pwd)"
FILE="$(basename "$DECK")"

# pick a free port in a high range
PORT=0
for p in 8899 8901 8911 8921 8931 8941; do
  if ! (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null; then PORT=$p; break; fi
done
[ "$PORT" = 0 ] && { echo "no free port" >&2; exit 1; }

cd "$DIR"
python3 -m http.server "$PORT" >/tmp/slide-deck-server.$PORT.log 2>&1 &
PID=$!
sleep 1
echo "URL  http://localhost:$PORT/$FILE"
echo "PID  $PID        # stop with:  kill $PID"
