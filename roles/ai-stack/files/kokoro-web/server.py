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

def _session():
    # No CPU memory arena: onnxruntime otherwise keeps every buffer it ever grew
    # (measured 2026-11-09: ~600 MB held, 557 MB of it pushed to swap on a box with
    # swap full). Two threads is plenty for one synthesis at a time.
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.enable_cpu_mem_arena = False
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    return ort.InferenceSession("/models/kokoro.onnx", sess_options=opts, providers=["CPUExecutionProvider"])


kokoro = Kokoro.from_session(_session(), "/models/voices.bin")
VOICES = sorted(v for v in kokoro.get_voices() if v[:1] in LANGS)
PAGE = (Path(__file__).parent / "index.html").read_text()
LOCK = asyncio.Semaphore(1)  # one synthesis at a time: small CPU box

app = FastAPI(title="AICORTEX Kokoro TTS", docs_url=None, redoc_url=None, openapi_url=None)


CHUNK_CHARS = 200  # memory peak follows the longest chunk, not the whole text


def _chunks(text: str) -> list[str]:
    """Split on sentence ends, then pack sentences into chunks of <= CHUNK_CHARS.
    Measured 2026-11-09: one 2000-char pass peaked at ~1.4 GB; a short one ~620 MB."""
    import re
    parts = [p.strip() for p in re.split(r"(?<=[.!?;:])\s+|\n+", text) if p.strip()]
    out, cur = [], ""
    for p in parts:
        while len(p) > CHUNK_CHARS:  # a run-on sentence: cut at the last space
            cut = p.rfind(" ", 0, CHUNK_CHARS)
            cut = cut if cut > 0 else CHUNK_CHARS
            if cur:
                out.append(cur); cur = ""
            out.append(p[:cut]); p = p[cut:].strip()
        if len(cur) + len(p) + 1 > CHUNK_CHARS and cur:
            out.append(cur); cur = p
        else:
            cur = (cur + " " + p).strip()
    if cur:
        out.append(cur)
    return out or [text]


def _synth_chunked(text: str, voice: str, speed: float, lang: str):
    import numpy as np
    pieces, rate = [], 24000
    for chunk in _chunks(text):
        samples, rate = kokoro.create(chunk, voice=voice, speed=speed, lang=lang)
        pieces.append(samples)
        pieces.append(np.zeros(int(rate * 0.12), dtype=samples.dtype))  # short pause between chunks
    return np.concatenate(pieces[:-1]), rate


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
        samples, rate = await asyncio.to_thread(_synth_chunked, req.text, req.voice, req.speed, lang)
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV")
    return Response(buf.getvalue(), media_type="audio/wav",
                    headers={"Content-Disposition": f'inline; filename="kokoro-{req.voice}.wav"'})
