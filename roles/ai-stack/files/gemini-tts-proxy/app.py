"""
gemini-tts-proxy: OpenAI-compatible /v1/audio/speech endpoint that translates to
Vertex AI generateContent for Gemini TTS models.

Why this exists: LiteLLM v1.80.x's speech-to-completion bridge auto-injects
thinkingLevel for any Gemini 3+ model name, which the TTS variant rejects with
HTTP 400. Direct Vertex calls work fine, so we proxy them here.
"""
from __future__ import annotations

import logging
import os
import struct
from base64 import b64decode
from typing import Optional

import google.auth
import google.auth.transport.requests
import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("gemini-tts-proxy")

PROJECT = os.environ["VERTEX_PROJECT"]
LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
PROXY_KEY = os.environ.get("PROXY_KEY") or None
ALLOWED = {
    m.strip()
    for m in os.environ.get(
        "MODEL_ALLOWLIST",
        "gemini-3.1-flash-tts-preview,"
        "gemini-2.5-flash-preview-tts,"
        "gemini-2.5-pro-preview-tts",
    ).split(",")
    if m.strip()
}

_credentials, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)

app = FastAPI(title="gemini-tts-proxy", version="1")


class SpeechRequest(BaseModel):
    model: str
    input: str
    voice: str = "Kore"
    response_format: Optional[str] = Field(default="wav")
    instructions: Optional[str] = None
    speed: Optional[float] = None  # accepted, ignored — Gemini TTS has no rate control


def _pcm16_to_wav(pcm: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    data_size = len(pcm)
    file_size = 36 + data_size
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        file_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        16,
        b"data",
        data_size,
    )
    return header + pcm


def _access_token() -> str:
    if not _credentials.valid:
        _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token


def _check_auth(authorization: Optional[str]) -> None:
    if not PROXY_KEY:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    if authorization.split(" ", 1)[1] != PROXY_KEY:
        raise HTTPException(401, "invalid token")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "models": sorted(ALLOWED)}


@app.get("/v1/models")
async def list_models(authorization: Optional[str] = Header(None)) -> dict:
    _check_auth(authorization)
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "owned_by": "google"} for m in sorted(ALLOWED)
        ],
    }


@app.post("/v1/audio/speech")
async def speech(req: SpeechRequest, authorization: Optional[str] = Header(None)):
    _check_auth(authorization)

    if req.model not in ALLOWED:
        raise HTTPException(400, f"model not in allowlist: {req.model}")

    text = req.input
    if req.instructions:
        text = f"{req.instructions}\n\n{text}"

    body = {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": req.voice}}
            },
        },
    }

    url = (
        f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
        f"/locations/{LOCATION}/publishers/google/models/{req.model}:generateContent"
    )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {_access_token()}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.HTTPError as e:
        log.exception("vertex network error")
        raise HTTPException(502, f"vertex network error: {e}") from e

    if r.status_code >= 400:
        log.error("vertex %s: %s", r.status_code, r.text[:1000])
        return JSONResponse(
            status_code=r.status_code,
            content={"error": {"upstream": "vertex_ai", "body": r.text}},
        )

    data = r.json()
    audio_b64 = None
    mime = "audio/l16; rate=24000"
    for part in data["candidates"][0]["content"]["parts"]:
        if "inlineData" in part:
            audio_b64 = part["inlineData"]["data"]
            mime = part["inlineData"].get("mimeType", mime)
            break
    if audio_b64 is None:
        raise HTTPException(502, "no audio returned by Vertex")

    pcm = b64decode(audio_b64)
    sample_rate = 24000
    if "rate=" in mime:
        try:
            sample_rate = int(mime.split("rate=", 1)[1].split(";", 1)[0].split(",", 1)[0])
        except ValueError:
            pass

    fmt = (req.response_format or "wav").lower()
    if fmt == "pcm":
        return Response(content=pcm, media_type="audio/pcm")
    if fmt not in {"wav", "mp3", "opus", "aac", "flac"}:
        fmt = "wav"
    if fmt != "wav":
        log.warning("requested %s — sidecar only emits wav, returning wav", fmt)
    wav = _pcm16_to_wav(pcm, sample_rate=sample_rate)
    return Response(content=wav, media_type="audio/wav")
