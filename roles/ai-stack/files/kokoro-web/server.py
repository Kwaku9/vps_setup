"""Kokoro TTS web page for AICORTEX: type text, pick a voice, hear it.

GET  /            the page
GET  /api/voices  voice ids grouped by language
POST /api/speak   {"text", "voice", "speed"} -> audio/wav
GET  /health      liveness
"""
import asyncio
import io
from pathlib import Path

import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from kokoro_onnx import Kokoro
from pydantic import BaseModel, Field

MAX_CHARS = 2000
# Kokoro voice id prefix -> (language label, espeak language code)
LANGS = {
    "a": ("American English", "en-us"), "b": ("British English", "en-gb"),
    "e": ("Spanish", "es"), "f": ("French", "fr-fr"), "h": ("Hindi", "hi"),
    "i": ("Italian", "it"), "p": ("Brazilian Portuguese", "pt-br"),
}

kokoro = Kokoro("/models/kokoro.onnx", "/models/voices.bin")
VOICES = sorted(v for v in kokoro.get_voices() if v[:1] in LANGS)
PAGE = (Path(__file__).parent / "index.html").read_text()
LOCK = asyncio.Semaphore(1)  # one synthesis at a time: small CPU box

app = FastAPI(title="AICORTEX Kokoro TTS", docs_url=None, redoc_url=None, openapi_url=None)


class Speak(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CHARS)
    voice: str
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


@app.get("/", response_class=HTMLResponse)
def page():
    return PAGE


@app.get("/health")
def health():
    return {"ok": True, "voices": len(VOICES)}


@app.get("/api/voices")
def voices():
    groups = {}
    for v in VOICES:
        label = LANGS[v[0]][0]
        gender = "female" if v[1:2] == "f" else "male"
        groups.setdefault(label, []).append({"id": v, "name": v.split("_", 1)[-1].title(), "gender": gender})
    return {"default": "af_heart" if "af_heart" in VOICES else VOICES[0], "groups": groups, "max_chars": MAX_CHARS}


@app.post("/api/speak")
async def speak(req: Speak):
    if req.voice not in VOICES:
        raise HTTPException(status_code=422, detail=f"Unknown voice '{req.voice}'.")
    lang = LANGS[req.voice[0]][1]
    async with LOCK:
        samples, rate = await asyncio.to_thread(kokoro.create, req.text, voice=req.voice, speed=req.speed, lang=lang)
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV")
    return Response(buf.getvalue(), media_type="audio/wav",
                    headers={"Content-Disposition": f'inline; filename="kokoro-{req.voice}.wav"'})
