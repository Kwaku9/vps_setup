#!/bin/bash
# Branding injection — runs BEFORE Open WebUI starts
# Lives on persistent data volume at /app/backend/data/branding-inject.sh
# Copies branded logo/favicon files from data volume into build/static and backend/static
# so that config.py copies our branded files instead of defaults.

DATA_DIR="/app/backend/data"
BUILD_STATIC="/app/build/static"
BACKEND_STATIC="/app/backend/open_webui/static"

# Only run if the branded logo exists on the data volume
if [ -f "$DATA_DIR/logo.png" ]; then
    echo "[Branding] Injecting branded assets..."

    # Logo files → build/static (source for config.py copy)
    for dest in logo.png favicon.png splash.png splash-dark.png favicon-dark.png; do
        cp "$DATA_DIR/logo.png" "$BUILD_STATIC/$dest" 2>/dev/null && echo "  $BUILD_STATIC/$dest"
    done
    cp "$DATA_DIR/logo.png" "/app/build/favicon.png" 2>/dev/null

    # Favicon variants → build/static
    for f in favicon.ico favicon.svg favicon-96x96.png apple-touch-icon.png; do
        [ -f "$DATA_DIR/$f" ] && cp "$DATA_DIR/$f" "$BUILD_STATIC/$f" 2>/dev/null && echo "  $BUILD_STATIC/$f"
    done

    # Custom CSS
    [ -f "$DATA_DIR/custom.css" ] && cp "$DATA_DIR/custom.css" "$BACKEND_STATIC/custom.css" 2>/dev/null && echo "  $BACKEND_STATIC/custom.css"

    echo "[Branding] Done — $(date -Iseconds)"
else
    echo "[Branding] No logo.png found in $DATA_DIR, skipping"
fi

# Start Open WebUI
exec bash start.sh
