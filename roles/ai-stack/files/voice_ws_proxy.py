"""
WebSocket proxy for Gemini Live voice sessions.

Validates the user's Open WebUI token (sk- API key or JWT), then relays
the WebSocket bidirectionally to LiteLLM's /vertex_ai/live endpoint
using the internal LiteLLM master key. No LLM keys are exposed to the client.

Injected into Open WebUI at startup via branding-inject.sh pattern.
Mount: app.websocket("/api/v1/voice/live")(voice_ws_proxy)
"""

import asyncio
import logging
import os

import aiohttp
from starlette.websockets import WebSocket, WebSocketState

log = logging.getLogger("open_webui.voice_proxy")

# Internal LiteLLM connection details (from Open WebUI env)
LITELLM_BASE = os.environ.get("OPENAI_API_BASE_URLS", "http://127.0.0.1:4000/v1")
LITELLM_BASE = LITELLM_BASE.split(";")[0].strip().rstrip("/v1").rstrip("/")
LITELLM_KEY = os.environ.get("OPENAI_API_KEYS", "").split(";")[0].strip()

# Vertex AI project config
VERTEX_PROJECT = os.environ.get("VERTEX_PROJECT", "aicortexi-web-search")
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")


async def _authenticate_ws(ws: WebSocket):
    """Validate the first message as an auth token. Returns user or None."""
    try:
        import json
        first_msg = await asyncio.wait_for(ws.receive_text(), timeout=10)
        data = json.loads(first_msg)
        token = data.get("token") or data.get("api_key") or ""

        if not token:
            await ws.close(code=4001, reason="No token provided")
            return None

        # Validate via Open WebUI's auth system
        from open_webui.utils.auth import get_current_user_by_api_key
        from types import SimpleNamespace

        # Create a minimal request object for the auth function
        request = SimpleNamespace()
        request.app = SimpleNamespace()

        # Import the app state
        from open_webui.main import app as owui_app
        request.app.state = owui_app.state

        user = get_current_user_by_api_key(request, token)
        if not user:
            await ws.close(code=4001, reason="Invalid token")
            return None

        return user
    except asyncio.TimeoutError:
        await ws.close(code=4001, reason="Auth timeout")
        return None
    except Exception as e:
        log.warning("Voice WS auth failed: %s", e)
        await ws.close(code=4001, reason="Auth failed")
        return None


async def voice_ws_proxy(ws: WebSocket):
    """Bidirectional WebSocket proxy: client <-> LiteLLM <-> Vertex AI."""
    await ws.accept()

    # Step 1: Authenticate
    user = await _authenticate_ws(ws)
    if not user:
        return

    log.info("Voice session started for user: %s", getattr(user, "name", "unknown"))

    # Step 2: Connect to LiteLLM's Vertex AI Live endpoint
    upstream_url = (
        f"ws://{LITELLM_BASE.replace('http://', '').replace('https://', '')}"
        f"/vertex_ai/live"
        f"?vertex_project={VERTEX_PROJECT}"
        f"&vertex_location={VERTEX_LOCATION}"
        f"&api_key={LITELLM_KEY}"
    )

    session = aiohttp.ClientSession()
    try:
        async with session.ws_connect(upstream_url) as upstream:

            async def client_to_upstream():
                """Forward client -> LiteLLM."""
                try:
                    while True:
                        msg = await ws.receive()
                        if msg["type"] == "websocket.disconnect":
                            break
                        elif "bytes" in msg and msg["bytes"]:
                            await upstream.send_bytes(msg["bytes"])
                        elif "text" in msg and msg["text"]:
                            await upstream.send_str(msg["text"])
                except Exception:
                    pass

            async def upstream_to_client():
                """Forward LiteLLM -> client."""
                try:
                    async for msg in upstream:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            await ws.send_bytes(msg.data)
                        elif msg.type == aiohttp.WSMsgType.TEXT:
                            await ws.send_text(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
                except Exception:
                    pass

            await asyncio.gather(
                client_to_upstream(),
                upstream_to_client(),
                return_exceptions=True,
            )
    except Exception as e:
        log.exception("Voice WS proxy error: %s", e)
        if ws.client_state != WebSocketState.DISCONNECTED:
            await ws.close(code=1011, reason="Upstream connection failed")
    finally:
        await session.close()
        try:
            if ws.client_state != WebSocketState.DISCONNECTED:
                await ws.close()
        except Exception:
            pass

    log.info("Voice session ended for user: %s", getattr(user, "name", "unknown"))
