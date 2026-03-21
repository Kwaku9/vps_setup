#!/usr/bin/env python3
"""Patch Open WebUI image model list to include all LiteLLM image models.
Run inside the open-webui container after startup."""

f = "/app/backend/open_webui/routers/images.py"
with open(f) as fh:
    code = fh.read()

old = '''        if request.app.state.config.IMAGE_GENERATION_ENGINE == "openai":
            return [
                {"id": "dall-e-2", "name": "DALL\u00b7E 2"},
                {"id": "dall-e-3", "name": "DALL\u00b7E 3"},
                {"id": "gpt-image-1", "name": "GPT-IMAGE 1"},
                {"id": "gpt-image-1.5", "name": "GPT-IMAGE 1.5"},
            ]'''

new = '''        if request.app.state.config.IMAGE_GENERATION_ENGINE == "openai":
            return [
                {"id": "dall-e-3", "name": "DALL-E 3"},
                {"id": "gpt-image-1", "name": "GPT Image 1"},
                {"id": "imagen-3", "name": "Imagen 3 (Vertex AI)"},
                {"id": "grok-imagine", "name": "Grok Imagine (xAI)"},
                {"id": "flux-klein", "name": "Flux Klein"},
                {"id": "gemini-2.5-flash-image", "name": "Gemini 2.5 Flash Image"},
                {"id": "gemini-3-pro-image", "name": "Gemini 3 Pro Image"},
                {"id": "gpt-5-image", "name": "GPT-5 Image"},
                {"id": "gpt-5-image-mini", "name": "GPT-5 Image Mini"},
            ]'''

if old in code:
    code = code.replace(old, new)
    with open(f, "w") as fh:
        fh.write(code)
    print("PATCHED - image model list updated")
else:
    print("ALREADY_PATCHED - no changes needed")
