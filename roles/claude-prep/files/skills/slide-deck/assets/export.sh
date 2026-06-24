#!/usr/bin/env bash
# export.sh — deck.html → deck.pdf (+ per-slide PNGs).
#
#   bash export.sh <deck.html>
#
# Primary path: decktape (renders reveal.js correctly, one page per slide).
# Fallback: headless Chrome printing reveal's built-in ?print-pdf view.
set -euo pipefail
DECK="${1:?usage: export.sh <deck.html>}"
[ -f "$DECK" ] || { echo "no such file: $DECK" >&2; exit 1; }
DIR="$(cd "$(dirname "$DECK")" && pwd)"; FILE="$(basename "$DECK")"
PDF="${DECK%.html}.pdf"

# serve (decktape and chrome both need http, not file://)
cd "$DIR"
PORT=8977; while (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; do PORT=$((PORT+1)); done
python3 -m http.server "$PORT" >/tmp/slide-deck-export.log 2>&1 &
SRV=$!; trap 'kill $SRV 2>/dev/null || true' EXIT
sleep 1
URL="http://localhost:$PORT/$FILE"

if command -v npx >/dev/null 2>&1; then
  echo "→ decktape: $URL → $PDF"
  npx -y decktape reveal "$URL" "$PDF" --screenshots --screenshots-directory "$DIR/slides" && {
    echo "✓ $PDF"; echo "✓ per-slide PNGs in $DIR/slides"; exit 0; }
  echo "decktape failed — trying headless Chrome fallback" >&2
fi

# fallback: reveal print-pdf via headless chrome
CHROME=""
for c in google-chrome chromium chromium-browser chrome; do
  command -v "$c" >/dev/null 2>&1 && { CHROME="$c"; break; }
done
[ -z "$CHROME" ] && { echo "no decktape and no chrome — install one" >&2; exit 1; }
echo "→ $CHROME --headless print-pdf"
"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$PDF" "$URL?print-pdf"
echo "✓ $PDF"
