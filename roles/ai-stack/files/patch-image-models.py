#!/usr/bin/env python3
"""Patch Open WebUI image model list to include all LiteLLM image models.
Run inside the open-webui container after startup.

Prints exactly one of APPLIED / UNCHANGED and exits 0, or prints ANCHOR_NOT_FOUND
and exits 1. Upstream reformatted images.py to single quotes in 0.11.x, which made
the old double-quoted anchor silently match nothing; a missing anchor must fail the
deploy, never report success.
"""
import sys

f = "/app/backend/open_webui/routers/images.py"
with open(f) as fh:
    code = fh.read()

# Anchor on the openai branch only, so the surrounding code (which moved between
# releases) is not part of the match.
old = """        if image_config.IMAGE_GENERATION_ENGINE == 'openai':
            return [
                {'id': 'dall-e-2', 'name': 'DALL·E 2'},
                {'id': 'dall-e-3', 'name': 'DALL·E 3'},
                {'id': 'gpt-image-1', 'name': 'GPT-IMAGE 1'},
                {'id': 'gpt-image-1.5', 'name': 'GPT-IMAGE 1.5'},
            ]"""

new = """        if image_config.IMAGE_GENERATION_ENGINE == 'openai':  # ANSIBLE-PATCH:image-models
            return [
                {'id': 'dall-e-3', 'name': 'DALL-E 3'},
                {'id': 'gpt-image-1', 'name': 'GPT Image 1'},
                {'id': 'imagen-3', 'name': 'Imagen 3 (Vertex AI)'},
                {'id': 'grok-imagine', 'name': 'Grok Imagine (xAI)'},
                {'id': 'flux-klein', 'name': 'Flux Klein'},
                {'id': 'gemini-2.5-flash-image', 'name': 'Gemini 2.5 Flash Image'},
                {'id': 'gemini-3-pro-image', 'name': 'Gemini 3 Pro Image'},
                {'id': 'gpt-5-image', 'name': 'GPT-5 Image'},
                {'id': 'gpt-5-image-mini', 'name': 'GPT-5 Image Mini'},
            ]"""

if "ANSIBLE-PATCH:image-models" in code:
    print("UNCHANGED")
elif code.count(old) == 1:
    compile(code.replace(old, new), f, "exec")  # refuse to write a syntax error
    with open(f, "w") as fh:
        fh.write(code.replace(old, new))
    print("APPLIED")
else:
    print("ANCHOR_NOT_FOUND: images.py openai model list changed upstream; update the anchor")
    sys.exit(1)
