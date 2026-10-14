#!/usr/bin/env python3
"""Inject the Gemini Live voice WS proxy route into Open WebUI main.py.

NOT wired into any playbook task (as of 2026-10-12): nothing calls it and no client
uses /api/v1/voice/live. To use it, podman cp this script and voice_ws_proxy.py into
the container's /tmp and run it, then restart Open WebUI.

Prints exactly one of APPLIED / UNCHANGED and exits 0, or prints a *_NOT_FOUND error
and exits 1. The previous version matched double quotes after upstream moved to single
quotes, printed "Target not found" and still exited 0, and the injected import sat in
try/except-pass, so a missing proxy module failed silently too.
"""
import os
import shutil
import sys

MAIN = "/app/backend/open_webui/main.py"
PROXY_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_ws_proxy.py")
PROXY_DST = "/app/backend/open_webui/routers/voice_ws_proxy.py"
MARK = "VOICE_WS_PROXY"

content = open(MAIN).read()

target = "    app.mount(\n        '/',\n        SPAStaticFiles(directory=FRONTEND_BUILD_DIR, html=True),"
inject = f"""    # {MARK} - Gemini Live voice relay through Open WebUI auth
    from open_webui.routers.voice_ws_proxy import voice_ws_proxy

    app.add_websocket_route('/api/v1/voice/live', voice_ws_proxy)

    app.mount(
        '/',
        SPAStaticFiles(directory=FRONTEND_BUILD_DIR, html=True),"""

if not os.path.exists(PROXY_SRC) and not os.path.exists(PROXY_DST):
    print(f"PROXY_NOT_FOUND: {PROXY_SRC} missing; copy voice_ws_proxy.py next to this script")
    sys.exit(1)

if MARK in content:
    print("UNCHANGED")
elif content.count(target) == 1:
    patched = content.replace(target, inject)
    compile(patched, MAIN, "exec")
    if os.path.exists(PROXY_SRC):
        shutil.copy(PROXY_SRC, PROXY_DST)
    open(MAIN, "w").write(patched)
    print("APPLIED")
else:
    print("ANCHOR_NOT_FOUND: main.py SPA mount block changed upstream; update the anchor")
    sys.exit(1)
