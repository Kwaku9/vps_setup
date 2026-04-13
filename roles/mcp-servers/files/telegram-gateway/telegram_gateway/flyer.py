"""Flyer generation handler for Telegram gateway.

Handles /flyer commands by:
1. Sending the user's description to LiteLLM to extract structured params
2. Running the flyer-generator container with those params
3. Sending the resulting PNG back via Telegram
"""

from __future__ import annotations

import json
import logging
import os

import httpx

from telegram_gateway.config import LITELLM_API_KEY, LITELLM_BASE_URL, LITELLM_DEFAULT_MODEL

logger = logging.getLogger(__name__)

FLYER_OUTPUT_DIR = os.environ.get("FLYER_OUTPUT_DIR", "/opt/podman-data/flyer-output")
FLYER_IMAGE = os.environ.get("FLYER_IMAGE", "flyer-generator:latest")

EXTRACTION_SYSTEM_PROMPT = """\
You are a flyer parameter extractor. The user will describe a flyer they want created.
Extract structured parameters and return ONLY valid JSON (no markdown, no explanation).

Available templates:
- "event-promo": For events, parties, launches, meetups. Params: event-name, event-tagline, event-date, event-time, event-venue, event-address, event-description, event-features (array), event-price, event-price-label, event-rsvp, event-contact, event-phone, event-website, event-organizer, event-note
- "announcement": For news, openings, services, offers. Params: title, subtitle, heading, body-text, features (array), price-1-label, price-1-amount, price-1-detail, price-2-label, price-2-amount, price-2-detail, notice-text, contact-heading, contact-email, contact-phone, contact-address, contact-website, footer-text
- "minimal": Simple message with strong typography. Params: title, subtitle, message, date, time, location, contact, footer-text

All templates support: color-bg (hex), color-accent (hex), color-secondary (hex)

Return JSON with this structure:
{
  "template": "event-promo",
  "output_name": "descriptive-filename",
  "params": { ... extracted params ... }
}

Rules:
- Pick the best template based on the description
- Only include params that have actual values from the user's description
- Use sensible defaults for event-tagline if the user doesn't specify one
- Keep text concise — this is a flyer, not an essay
- output_name should be kebab-case, descriptive, no spaces
"""


async def extract_flyer_params(description: str) -> dict:
    """Use LiteLLM to extract structured flyer params from a description."""
    url = f"{LITELLM_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LITELLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LITELLM_DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": description},
        ],
        "temperature": 0.3,
        "max_tokens": 1500,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)

    return json.loads(content)


PODMAN_SOCKET = os.environ.get("PODMAN_SOCKET", "/run/podman/podman.sock")


async def run_flyer_container(flyer_spec: dict) -> dict:
    """Run the flyer-generator container via Podman API socket and return result."""
    spec_json = json.dumps(flyer_spec)
    image = FLYER_IMAGE

    # Create container via Podman API
    create_body = {
        "image": image,
        "command": ["python3", "/app/generate.py", spec_json],
        "mounts": [
            {
                "destination": "/app/output",
                "type": "bind",
                "source": FLYER_OUTPUT_DIR,
                "options": ["rw", "Z"],
            }
        ],
        "remove": True,
    }

    transport = httpx.AsyncHTTPTransport(uds=PODMAN_SOCKET)
    async with httpx.AsyncClient(transport=transport, base_url="http://d", timeout=120) as client:
        # Create container
        resp = await client.post(
            "/v5.0.0/libpod/containers/create",
            json=create_body,
        )
        if resp.status_code not in (200, 201):
            return {"error": f"Container create failed: {resp.text[:500]}"}
        container_id = resp.json().get("Id")

        # Start container
        resp = await client.post(f"/v5.0.0/libpod/containers/{container_id}/start")
        if resp.status_code not in (200, 204):
            return {"error": f"Container start failed: {resp.text[:500]}"}

        # Wait for container to finish
        resp = await client.post(
            f"/v5.0.0/libpod/containers/{container_id}/wait",
            timeout=120,
        )
        if resp.status_code != 200:
            return {"error": f"Container wait failed: {resp.text[:500]}"}

        wait_result = resp.json()
        exit_code = wait_result.get("StatusCode", -1) if isinstance(wait_result, dict) else int(wait_result)

        # Get logs (stdout)
        resp = await client.get(
            f"/v5.0.0/libpod/containers/{container_id}/logs",
            params={"stdout": True, "stderr": True},
        )
        # Podman log output has stream headers — extract text
        raw_logs = resp.text
        # Strip podman log stream prefixes (8-byte headers per line)
        lines = []
        for line in raw_logs.split("\n"):
            # Podman API logs may have binary prefixes; try to extract JSON
            if "{" in line:
                lines.append(line[line.index("{"):])
        log_output = "\n".join(lines)

        if exit_code != 0:
            logger.error("Flyer container exited %d: %s", exit_code, log_output[:500])
            return {"error": f"Container exited with code {exit_code}: {log_output[:500]}"}

        try:
            return json.loads(log_output)
        except json.JSONDecodeError:
            return {"error": f"Invalid output: {log_output[:500]}"}


async def handle_flyer_command(chat_id: int, description: str) -> dict:
    """Full pipeline: description → params → container → PNG path.

    Returns dict with 'png', 'pdf', or 'error' key.
    """
    if not description:
        return {
            "error": (
                "Please describe the flyer you want. Example:\n"
                "<code>/flyer Summer pool party at Haven on Peachwood, "
                "July 12th at 8pm, $15 entry, live DJ, food trucks</code>"
            )
        }

    # Step 1: Extract params via LLM
    try:
        flyer_spec = await extract_flyer_params(description)
    except Exception as e:
        logger.exception("Failed to extract flyer params")
        return {"error": f"Could not parse flyer description: {e}"}

    # Ensure format is PNG
    flyer_spec["format"] = "png"

    # Step 2: Run container
    try:
        result = await run_flyer_container(flyer_spec)
    except httpx.TimeoutException:
        return {"error": "Flyer generation timed out (120s limit)."}
    except Exception as e:
        logger.exception("Flyer container error")
        return {"error": f"Generation failed: {e}"}

    if "error" in result:
        return result

    # Step 3: Map container paths to host paths
    png_path = result.get("png")
    pdf_path = result.get("pdf")

    if png_path:
        # Container outputs to /app/output, host has FLYER_OUTPUT_DIR
        png_path = png_path.replace("/app/output", FLYER_OUTPUT_DIR)
    if pdf_path:
        pdf_path = pdf_path.replace("/app/output", FLYER_OUTPUT_DIR)

    return {
        "png": png_path,
        "pdf": pdf_path,
        "template": result.get("template"),
        "params": result.get("params"),
    }
