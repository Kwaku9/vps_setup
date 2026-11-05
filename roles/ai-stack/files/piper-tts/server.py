"""piper-tts: an OpenAI-compatible text-to-speech endpoint backed by Piper (CPU, ONNX), in kokoro-tts's place.

POST /v1/audio/speech  {"input": ..., "model": any, "voice": any, "response_format": "mp3" | "wav"}  -> audio
GET  /health, GET /v1/models

Every client keeps the request it already sends: any model name is accepted and any voice name maps to the one
configured Piper voice (OpenWebUI sent "kokoro"/"af_heart"; the Telegram bot still sends model "kokoro" and asks for
mp3). Standard library HTTP only; the one synthesis call is serialised behind a lock (Piper is fast: ~6x realtime on
this CPU, so a queue never builds for a single user).
"""
import io
import json
import os
import signal
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FORMATS = {"mp3": "audio/mpeg", "wav": "audio/wav"}


def _pcm(voice, text):
    chunks = list(voice.synthesize(text))
    if not chunks:
        raise ValueError("no audio produced")
    return b"".join(c.audio_int16_bytes for c in chunks), chunks[0].sample_rate


def _wav(pcm, rate):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _mp3(pcm, rate):
    import lameenc  # imported here so the unit tests need no encoder unless they exercise mp3
    enc = lameenc.Encoder()
    enc.set_bit_rate(64)
    enc.set_in_sample_rate(rate)
    enc.set_channels(1)
    enc.set_quality(2)
    return enc.encode(pcm) + enc.flush()


def make_server(host, port, voice, voice_name, max_chars=4000):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "piper-tts"

        def _send(self, code, body, ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # one short line per request, no request bodies (they hold user text)
            print("%s %s" % (self.command, self.path), flush=True)

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"status": "ok", "voice": voice_name})
            if self.path == "/v1/models":
                return self._send(200, {"object": "list", "data": [{"id": "piper", "object": "model"}]})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/v1/audio/speech":
                return self._send(404, {"error": "not found"})
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError:
                return self._send(400, {"error": "body must be JSON"})
            text = str(req.get("input") or "").strip()
            fmt = str(req.get("response_format") or "mp3").lower()
            if not text:
                return self._send(400, {"error": "input is empty"})
            if fmt not in FORMATS:
                return self._send(400, {"error": "response_format must be one of: %s" % ", ".join(FORMATS)})
            text = text[:max_chars]
            try:
                with lock:
                    pcm, rate = _pcm(voice, text)
                audio = _mp3(pcm, rate) if fmt == "mp3" else _wav(pcm, rate)
            except Exception as e:  # noqa: BLE001 - report, never crash the server
                return self._send(500, {"error": "synthesis failed: %s" % type(e).__name__})
            return self._send(200, audio, FORMATS[fmt])

    return ThreadingHTTPServer((host, port), Handler)


def install_signal_handlers():
    """Exit promptly on SIGTERM: as PID 1 in a container Python would otherwise ignore it and every stop would wait out
    podman's 10 s timeout and end in SIGKILL."""
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))


def main():
    install_signal_handlers()
    from piper import PiperVoice
    model = os.environ.get("PIPER_VOICE_PATH", "/voices/en_US-amy-medium.onnx")
    voice = PiperVoice.load(model)
    name = os.path.basename(model).rsplit(".onnx", 1)[0]
    httpd = make_server(os.environ.get("HOST", "0.0.0.0"), int(os.environ.get("PORT", "8880")), voice, name,
                        int(os.environ.get("MAX_CHARS", "4000")))
    print("piper-tts serving %s on :%d" % (name, httpd.server_address[1]), flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
