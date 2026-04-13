"""Inject voice WS proxy route into Open WebUI main.py"""
MAIN = "/app/backend/open_webui/main.py"
content = open(MAIN).read()

# Remove old injection if present
if "VOICE_WS_PROXY" in content:
    lines = content.split("\n")
    new_lines = []
    skip = False
    for line in lines:
        if "VOICE_WS_PROXY" in line:
            skip = True
            continue
        if skip and (line.strip().startswith("try:") or line.strip().startswith("from ") or line.strip().startswith("app.") or line.strip().startswith("except") or line.strip() == "pass" or line.strip() == ""):
            continue
        skip = False
        new_lines.append(line)
    content = "\n".join(new_lines)

# Inject using add_websocket_route before the SPA mount
target = '    app.mount(\n        "/",\n        SPAStaticFiles(directory=FRONTEND_BUILD_DIR, html=True),'
inject = """    # VOICE_WS_PROXY — Gemini Live voice relay through Open WebUI auth
    try:
        from open_webui.routers.voice_ws_proxy import voice_ws_proxy
        app.add_websocket_route("/api/v1/voice/live", voice_ws_proxy)
    except Exception:
        pass

    app.mount(
        "/",
        SPAStaticFiles(directory=FRONTEND_BUILD_DIR, html=True),"""

if target in content:
    content = content.replace(target, inject)
    open(MAIN, "w").write(content)
    print("Injected before SPA mount with add_websocket_route")
else:
    print("Target not found — check main.py structure")
