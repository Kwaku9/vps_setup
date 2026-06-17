from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone

import httpx
from opentelemetry import trace

from telegram_gateway.config import (
    CLAUDE_ALLOWED_TOOLS,
    CLAUDE_CLI_PATH,
    CLAUDE_CLI_TIMEOUT,
    CLAUDE_MCP_CONFIG,
    KOKORO_TTS_URL,
    LITELLM_API_KEY,
    LITELLM_BASE_URL,
    LITELLM_DEFAULT_MODEL,
)
from telegram_gateway import db

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _strip_for_tts(text: str) -> str:
    """Strip HTML tags, code blocks, and markdown for clean TTS input."""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove code blocks (replace with brief mention)
    text = re.sub(r"```[\s\S]*?```", " [code block] ", text)
    text = re.sub(r"`[^`]+`", "", text)
    # Remove markdown bold/italic markers
    text = re.sub(r"\*+([^*]+)\*+", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    # Unescape HTML entities
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def synthesize_tts(text: str, voice: str = "af_heart") -> str | None:
    """Call Kokoro TTS and return path to a temp OGG/Opus audio file.

    Returns the file path on success, or None on failure.
    The caller is responsible for deleting the temp file.
    """
    clean_text = _strip_for_tts(text)
    if not clean_text or len(clean_text) < 3:
        return None

    # Truncate very long responses — Kokoro has limits and very long audio
    # is impractical for Telegram voice messages
    if len(clean_text) > 1500:
        clean_text = clean_text[:1500] + "... see the full text above."
    # Pad with trailing silence marker so final words aren't cut off
    clean_text += " ..."

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{KOKORO_TTS_URL}/v1/audio/speech",
                json={
                    "model": "kokoro",
                    "input": clean_text,
                    "voice": voice,
                    "response_format": "mp3",
                },
            )
            if resp.status_code != 200:
                logger.warning("Kokoro TTS returned %d: %s", resp.status_code, resp.text[:200])
                return None

            # Write audio bytes to temp file
            fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
            try:
                os.write(fd, resp.content)
            finally:
                os.close(fd)

            logger.info("TTS synthesized %d chars → %s (%d bytes)", len(clean_text), tmp_path, len(resp.content))
            return tmp_path

    except Exception:
        logger.exception("TTS synthesis failed")
        return None


async def process_command(command_id: int):
    """Process a command using the configured backend (claude-cli or litellm)."""
    pool = await db.get_pool()
    cmd = await pool.fetchrow(
        "SELECT * FROM gateway.commands WHERE id = $1", command_id
    )
    if not cmd:
        logger.error("Command %d not found", command_id)
        return

    agent_type = cmd["agent_type"]
    config = await db.get_agent_config(agent_type)

    backend = config["backend"] if config else "claude-cli"
    system_prompt = config["system_prompt"] if config else "You are a helpful assistant."
    model = config["model"] if config else LITELLM_DEFAULT_MODEL
    max_tokens = config["max_tokens"] if config else 4096

    # APM: append manager profile to system prompt if onboarding is complete
    if agent_type == "apm":
        chat_id = cmd["telegram_chat_id"]
        profile = await db.get_manager_profile(chat_id)
        if profile and profile["onboarding_done"]:
            system_prompt += f"\n\nMANAGER PROFILE (from onboarding):\n{profile['profile']}"

    tts_enabled = config["tts_enabled"] if config else False
    tts_voice = config["tts_voice"] if config else "af_heart"

    with tracer.start_as_current_span(
        "command.processing",
        attributes={
            "command.id": command_id,
            "command.agent_type": agent_type,
            "command.backend": backend,
            "command.model": model,
        },
    ):
        if backend == "litellm":
            await _process_litellm(
                command_id, cmd, agent_type, system_prompt, model, max_tokens
            )
        else:
            await _process_claude_cli(
                command_id, cmd, agent_type, system_prompt, model
            )

        # TTS: synthesize voice and send after text responses
        if tts_enabled:
            await _send_tts_response(command_id, cmd, agent_type, tts_voice)


async def _send_tts_response(
    command_id: int,
    cmd,
    agent_type: str,
    voice: str,
):
    """Collect the text responses for a command, synthesize via Kokoro TTS,
    and store the voice response for delivery to Telegram."""
    from telegram_gateway.bot import send_telegram_audio

    chat_id = cmd["telegram_chat_id"]

    # Collect all text blocks for this command
    pool = await db.get_pool()
    rows = await pool.fetch(
        """
        SELECT content FROM gateway.responses
        WHERE command_id = $1
          AND response_type = 'text'
        ORDER BY id ASC
        """,
        command_id,
    )

    if not rows:
        return

    # Combine all text blocks into one TTS input
    combined = " ".join(row["content"] for row in rows)

    tmp_path = await synthesize_tts(combined, voice)
    if not tmp_path:
        return

    try:
        await send_telegram_audio(chat_id, tmp_path, title="APM Voice Response")
        logger.info("TTS voice sent for command %d to chat %d", command_id, chat_id)
    except Exception:
        logger.exception("Failed to send TTS voice for command %d", command_id)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _parse_text_into_blocks(text: str) -> list[tuple[str, str]]:
    """Parse a plain text response into typed blocks.

    Splits code blocks from prose so each gets its own response_type.
    Returns list of (response_type, content) tuples.
    """
    blocks: list[tuple[str, str]] = []
    # Split on fenced code blocks: ```lang\n...\n```
    parts = re.split(r"(```[\w]*\n.*?\n```)", text, flags=re.DOTALL)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("```"):
            blocks.append(("code", part))
        else:
            blocks.append(("text", part))
    return blocks if blocks else [("text", text)]


def _extract_blocks_from_json(data: dict) -> list[tuple[str, str]]:
    """Extract typed content blocks from Claude CLI JSON output.

    The --output-format json output contains a 'result' field with the
    response text. It may also contain 'content' blocks with types.
    We parse these into (response_type, content) tuples for distinct
    Telegram formatting.
    """
    blocks: list[tuple[str, str]] = []

    # Try structured content blocks first (stream-json / newer format)
    content_blocks = data.get("content", [])
    if isinstance(content_blocks, list) and content_blocks:
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "text")
            if btype == "thinking":
                text = block.get("thinking", "") or block.get("text", "")
                if text:
                    blocks.append(("thinking", text))
            elif btype == "tool_use":
                name = block.get("name", "unknown")
                inp = json.dumps(block.get("input", {}), indent=2)
                blocks.append(("tool_use", f"{name}\n{inp}"))
            elif btype == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        c.get("text", str(c)) for c in content
                    )
                blocks.append(("tool_result", str(content)))
            elif btype == "text":
                text = block.get("text", "")
                if text:
                    # Further split text that contains embedded code blocks
                    blocks.extend(_parse_text_into_blocks(text))

    # Fallback: use the 'result' string
    if not blocks:
        result = data.get("result", "")
        if result:
            blocks = _parse_text_into_blocks(result)

    return blocks


def _resolve_no_output(
    blocks: "list[tuple[str, str]]",
    stderr_text: str,
    has_session: bool,
) -> "tuple[list[tuple[str, str]], bool]":
    """Decide user-facing blocks + whether to clear a stale session.

    `claude --resume <id>` returns empty stdout + "No conversation found ..."
    on stderr when the stored session can't be resumed from the gateway's
    cwd/project (e.g. it was created under a different working directory, or
    pruned). Without clearing the stored session id the chat is stuck forever,
    so detect that case and signal a reset — the next message then starts a
    fresh session. Mirrors the self-heal coder.py already has.

    Returns (blocks, clear_session).
    """
    if blocks:
        return blocks, False
    if has_session and "No conversation found" in stderr_text:
        return ([("text",
                  "Your previous session expired and has been reset — "
                  "send your message again.")], True)
    return [("text", "(No output from Claude CLI)")], False


async def _process_claude_cli(
    command_id: int,
    cmd,
    agent_type: str,
    system_prompt: str,
    model: str,
):
    """Run the message through Claude Code CLI with session continuity.

    First message in a chat creates a new session.
    Subsequent messages resume the existing session via --resume.
    Output is captured as JSON to extract structured content blocks.
    Each block type (text, code, thinking, tool_use, tool_result) is
    stored as a separate response row for distinct Telegram formatting.
    """
    chat_id = cmd["telegram_chat_id"]
    prompt = cmd["message"]

    # Look up existing session for this chat
    session = await db.get_session(chat_id)

    # Build CLI args
    cli_args = [CLAUDE_CLI_PATH]
    if session and session["session_id"]:
        cli_args.extend(["--resume", session["session_id"]])
        cli_args.extend(["-p", prompt])
    else:
        # New session — include system prompt as context
        full_prompt = f"[Context: {system_prompt}]\n\n{prompt}"
        cli_args.extend(["-p", full_prompt])

    cli_args.extend(["--model", model, "--output-format", "json"])

    # Optional dedicated MCP config (e.g. the neo4j service-map graph). --mcp-config
    # is variadic so it must precede --strict-mcp-config; --allowed-tools is variadic
    # too, so it goes last (it consumes the trailing tool names).
    if CLAUDE_MCP_CONFIG:
        cli_args.extend(["--mcp-config", CLAUDE_MCP_CONFIG, "--strict-mcp-config"])
        tools = [t.strip() for t in CLAUDE_ALLOWED_TOOLS.split(",") if t.strip()]
        if tools:
            cli_args.append("--allowed-tools")
            cli_args.extend(tools)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cli_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="/workspace/vscode-projects/vps_setup",
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=CLAUDE_CLI_TIMEOUT
        )

        raw_output = stdout.decode("utf-8", errors="replace").strip()
        blocks: list[tuple[str, str]] = []
        new_session_id = None

        if raw_output:
            try:
                data = json.loads(raw_output)
                new_session_id = data.get("session_id")
                blocks = _extract_blocks_from_json(data)
            except json.JSONDecodeError:
                # Plain text fallback
                blocks = _parse_text_into_blocks(raw_output)

        # Always forward stderr as a separate response for visibility
        if stderr:
            err = stderr.decode("utf-8", errors="replace").strip()
            if err:
                await db.insert_response(
                    command_id=command_id,
                    agent_type=agent_type,
                    response_type="stderr",
                    content=err,
                    chat_id=chat_id,
                    payload={
                        "backend": "claude-cli",
                        "exit_code": proc.returncode or 0,
                    },
                )

        # Self-heal: if the CLI produced nothing because --resume hit a session
        # that no longer exists in this project/cwd, clear the stale pointer so
        # the next message starts fresh (otherwise the chat is stuck forever).
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
        blocks, clear_session = _resolve_no_output(
            blocks, stderr_text, session is not None)
        if clear_session:
            await db.delete_session(chat_id)
            logger.info(
                "Cleared stale session for chat %d (No conversation found)",
                chat_id)

        # Store/update session for continuity
        if new_session_id:
            await db.upsert_session(chat_id, new_session_id, agent_type)
            logger.info("Session %s stored for chat %d", new_session_id, chat_id)
        elif session:
            await db.touch_session(chat_id)

        span = trace.get_current_span()
        span.set_attribute("cli.exit_code", proc.returncode or 0)
        span.set_attribute("cli.block_count", len(blocks))
        span.set_attribute("cli.session_resumed", session is not None)
        if new_session_id:
            span.set_attribute("cli.session_id", new_session_id)

        # APM: extract and save profile if agent emitted [PROFILE_SAVE] tag
        if agent_type == "apm":
            saved_blocks = []
            for response_type, content in blocks:
                match = re.search(
                    r"\[PROFILE_SAVE\](.*?)\[/PROFILE_SAVE\]",
                    content,
                    re.DOTALL,
                )
                if match:
                    profile_text = match.group(1).strip()
                    await db.upsert_manager_profile(chat_id, profile_text)
                    logger.info("Saved manager profile for chat %d", chat_id)
                    # Remove the tag from the message sent to the user
                    cleaned = re.sub(
                        r"\[PROFILE_SAVE\].*?\[/PROFILE_SAVE\]",
                        "",
                        content,
                        flags=re.DOTALL,
                    ).strip()
                    if cleaned:
                        saved_blocks.append((response_type, cleaned))
                else:
                    saved_blocks.append((response_type, content))
            blocks = saved_blocks

        # Insert each block as a separate response for distinct formatting
        for response_type, content in blocks:
            await db.insert_response(
                command_id=command_id,
                agent_type=agent_type,
                response_type=response_type,
                content=content,
                chat_id=chat_id,
                payload={
                    "backend": "claude-cli",
                    "session_id": new_session_id or (session["session_id"] if session else None),
                },
            )

        await db.update_command_status(
            command_id, "completed",
            completed_at=datetime.now(timezone.utc),
        )
        logger.info(
            "Command %d completed via claude-cli (%d blocks, session=%s)",
            command_id, len(blocks),
            new_session_id or (session["session_id"] if session else "new"),
        )

    except asyncio.TimeoutError:
        logger.error("Claude CLI timeout for command %d (>%ds)", command_id, CLAUDE_CLI_TIMEOUT)
        raise
    except FileNotFoundError:
        logger.error("Claude CLI not found at %s, falling back to litellm", CLAUDE_CLI_PATH)
        config = await db.get_agent_config(agent_type)
        model = config["model"] if config else LITELLM_DEFAULT_MODEL
        max_tokens = config["max_tokens"] if config else 4096
        system_prompt_fb = config["system_prompt"] if config else "You are a helpful assistant."
        await _process_litellm(
            command_id, cmd, agent_type, system_prompt_fb, model, max_tokens
        )


async def _process_litellm(
    command_id: int,
    cmd,
    agent_type: str,
    system_prompt: str,
    model: str,
    max_tokens: int,
):
    """Call LiteLLM gateway (OpenAI-compatible API)."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            headers = {"Content-Type": "application/json"}
            if LITELLM_API_KEY:
                headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"

            resp = await client.post(
                f"{LITELLM_BASE_URL}/v1/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": cmd["message"]},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        if not content:
            content = "(No response generated)"

        usage = data.get("usage", {})
        span = trace.get_current_span()
        span.set_attribute("tokens.input", usage.get("prompt_tokens", 0))
        span.set_attribute("tokens.output", usage.get("completion_tokens", 0))

        # Parse text into blocks for consistent formatting
        blocks = _parse_text_into_blocks(content)
        for response_type, block_content in blocks:
            await db.insert_response(
                command_id=command_id,
                agent_type=agent_type,
                response_type=response_type,
                content=block_content,
                chat_id=cmd["telegram_chat_id"],
                payload={
                    "backend": "litellm",
                    "model": data.get("model", model),
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                },
            )

        await db.update_command_status(
            command_id, "completed",
            completed_at=datetime.now(timezone.utc),
        )

        logger.info(
            "Command %d completed via litellm: %d input, %d output tokens",
            command_id,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )

    except httpx.HTTPStatusError as e:
        logger.error("LiteLLM API error for command %d: %s", command_id, e)
        raise
    except httpx.TimeoutException:
        logger.error("LiteLLM timeout for command %d", command_id)
        raise
