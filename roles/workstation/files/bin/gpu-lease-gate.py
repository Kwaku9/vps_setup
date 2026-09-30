#!/usr/bin/env python3
"""Admission control in front of Ollama, using ARCHIVIST's GPU lease.

WHY THIS EXISTS
Ollama was the one GPU tenant on this laptop that took the card without
asking. Every other one negotiates: ARCHIVIST's caption and embed passes hold
a machine-wide flock lease and check free VRAM before loading
(src/archivist/gpu.py), and archivist-sync.sh stops rerank-gpu for its window
and restores it on the way out. Ollama just loads, and when the card is full
it does not fail -- it silently offloads to the CPU and keeps serving.

Measured 2026-09-30, with archivist-vlm mid-batch holding 3,978 MiB of the
6,144 MiB card: qwen3:1.7b loaded 3% on GPU / 97% on CPU (0.06 GB of 1.90 GB
in VRAM) and answered one 8-passage RAG question in 199 SECONDS -- 1,911
prompt tokens at 60.7 tok/s prefill, then 92 output tokens at 0.5 tok/s. The
answer was correct and properly grounded. It was the latency that made it
useless, and nothing anywhere reported that the GPU had not been used.

A refusal would have been strictly better than that answer: the browser has a
working WebLLM path on the same GPU, and the caller can fall back to it in
milliseconds if it is told. So this gate turns the silent CPU spill into an
explicit 503, using the same lease the rest of the estate already respects.

WHAT IT DOES NOT DO
It does not make the GPU bigger and it does not queue. A refused request is
refused, exactly as `gpu_lease` refuses ARCHIVIST ("a refused GPU lease is a
skipped stage, not a failure"). Callers are expected to have somewhere else
to go.

It also cannot protect against whisper-gpu, which sits at ~90 MiB idle and
spikes to ~1.3-2.0 GB the moment push-to-talk is pressed. That spike can land
after this gate has already admitted a request. gpu.py's own header warns
about the same thing. The required-MiB defaults below carry headroom for it,
but headroom is not a guarantee, and no admission check can be.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("GATE_UPSTREAM", "http://127.0.0.1:11434").rstrip("/")
LISTEN_HOST = os.environ.get("GATE_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("GATE_PORT", "11435"))

# The SAME lock ARCHIVIST uses. Hardcoding a second path would create two
# leases that cannot see each other, which is the bug this is fixing.
# Default matches archivist/config.py GpuConfig.semaphore_lock_path.
_runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
LOCK_PATH = os.environ.get("GATE_LOCK_PATH", f"{_runtime}/archivist-gpu.lock")

# Free VRAM (MiB) a model must see before it is allowed to load, same shape and
# spirit as archivist's GpuConfig.min_free_mib. Measured 2026-09-30 via
# /api/ps: qwen3:1.7b reports total=1.90GB resident at ctx 4096. 2200 leaves
# ~300 MiB over that; 3900 covers qwen3.5:4b (~3.4GB weights) the same way.
# Probe, never assume: /api/ps reports what a model ACTUALLY took, so re-read
# it after changing a model or a context size rather than trusting this table.
DEFAULT_REQUIRED_MIB = {
    "qwen3:1.7b": 2200,
    "qwen3.5:4b": 3900,
    "gemma4:e4b": 5200,
}
FALLBACK_REQUIRED_MIB = int(os.environ.get("GATE_DEFAULT_REQUIRED_MIB", "2200"))


def _load_required_table() -> dict[str, int]:
    raw = os.environ.get("GATE_REQUIRED_MIB", "").strip()
    if not raw:
        return dict(DEFAULT_REQUIRED_MIB)
    # "model=mib,model=mib" -- deliberately not JSON, so it stays writable in a
    # systemd Environment= line without quoting games.
    table = dict(DEFAULT_REQUIRED_MIB)
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        name, _, mib = pair.partition("=")
        try:
            table[name.strip()] = int(mib)
        except ValueError:
            pass
    return table


REQUIRED_MIB = _load_required_table()

# Forced onto every gated request. Ollama holds a model resident for
# keep_alive AFTER the response ends, so releasing the lease at end-of-response
# while the weights are still on the card would report the GPU free when it is
# not -- exactly the false signal this gate exists to remove. keep_alive=0
# makes the release honest: VRAM is returned when the answer is.
#
# The cost is a reload per question (1.4GB from page cache, seconds). The
# ollama.container quadlet chose 30s for the opposite reason, to keep a
# conversation warm. Set GATE_KEEP_ALIVE=30s to restore that, accepting that
# the lease then only approximates residency.
KEEP_ALIVE = os.environ.get("GATE_KEEP_ALIVE", "0")

GATED_PATHS = {"/api/chat", "/api/generate"}
PASSTHROUGH_PATHS = {"/api/tags", "/api/ps", "/api/version", "/api/show"}

# Mirrors OLLAMA_ORIGINS in ollama.container. The browser now talks to this
# gate, so the gate has to answer the preflight; Ollama's own allowlist no
# longer sees the request's Origin.
_origins = os.environ.get(
    "GATE_ORIGINS",
    "https://rag.demo.nucybersec.com,https://nucybersec-rag-demo.web.app,"
    "https://fedora.taila30e7d.ts.net:*,http://localhost:*,http://127.0.0.1:*",
)
ALLOWED_ORIGINS = [o.strip() for o in _origins.split(",") if o.strip()]


def origin_allowed(origin: str) -> bool:
    if not origin:
        return False
    for pattern in ALLOWED_ORIGINS:
        if pattern == origin:
            return True
        # Only a trailing ":*" port wildcard is supported, which is the only
        # form Ollama's own list uses. Not a general glob: "*" alone would
        # allow every origin on the internet to drive this GPU.
        if pattern.endswith(":*") and origin.startswith(pattern[:-1]):
            rest = origin[len(pattern) - 1:]
            if rest.isdigit():
                return True
    return False


class GpuBusy(RuntimeError):
    """Another lease holder has the card. Same meaning as archivist.gpu.GpuBusy."""


class InsufficientVram(RuntimeError):
    """Residents leave too little free. Same meaning as archivist.gpu."""


def free_vram_mib() -> int:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    return int(out.stdout.strip().splitlines()[0])


def acquire_lease(required_mib: int) -> int:
    """Take the machine-wide lease, then verify headroom. Returns the fd.

    Deliberately the same order as archivist.gpu.gpu_lease: lock first, probe
    second. Probing first would race -- another tenant can load between the
    probe and the lock, and then the number that authorized the request
    describes a card that no longer exists.
    """
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise GpuBusy(f"another GPU job holds {LOCK_PATH}") from e
        free = free_vram_mib()
        if free < required_mib:
            raise InsufficientVram(f"need {required_mib} MiB, only {free} MiB free")
        return fd
    except Exception:
        os.close(fd)  # releases the flock if we took it
        raise


def required_for(model: str) -> int:
    return REQUIRED_MIB.get(model, FALLBACK_REQUIRED_MIB)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "gpu-lease-gate"

    def log_message(self, fmt, *args):  # noqa: A002
        sys.stderr.write("[gate] %s\n" % (fmt % args))

    # --- helpers ---------------------------------------------------------
    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/gpu-lease":
            return self._lease_status()
        if self.path.split("?")[0] in PASSTHROUGH_PATHS:
            return self._proxy(gated=False)
        return self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in GATED_PATHS:
            return self._proxy(gated=True)
        if path in PASSTHROUGH_PATHS:
            return self._proxy(gated=False)
        return self._json(404, {"error": "not found"})

    def _lease_status(self):
        """Would an answer be admitted right now? Non-destructive probe.

        Takes and immediately drops the lease. That makes the answer a snapshot,
        not a reservation -- it can be wrong by the time a caller acts on it.
        It exists so a UI can show state without provoking a 503, not as a
        substitute for handling one.
        """
        model = "qwen3:1.7b"
        req = required_for(model)
        try:
            fd = acquire_lease(req)
        except GpuBusy as e:
            return self._json(200, {"admit": False, "reason": "gpu_busy",
                                    "detail": str(e), "required_mib": req})
        except InsufficientVram as e:
            return self._json(200, {"admit": False, "reason": "insufficient_vram",
                                    "detail": str(e), "required_mib": req,
                                    "free_mib": free_vram_mib()})
        except Exception as e:
            return self._json(200, {"admit": False, "reason": "probe_failed",
                                    "detail": str(e), "required_mib": req})
        try:
            return self._json(200, {"admit": True, "reason": "ok",
                                    "required_mib": req, "free_mib": free_vram_mib()})
        finally:
            os.close(fd)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _proxy(self, *, gated: bool):
        body = self._read_body()
        model = ""
        if gated and body:
            try:
                parsed = json.loads(body)
                model = str(parsed.get("model", ""))
                if KEEP_ALIVE != "":
                    ka = KEEP_ALIVE
                    parsed["keep_alive"] = int(ka) if ka.lstrip("-").isdigit() else ka
                    body = json.dumps(parsed).encode()
            except (ValueError, TypeError):
                return self._json(400, {"error": "gated request body must be JSON"})

        fd = None
        if gated:
            req = required_for(model)
            try:
                fd = acquire_lease(req)
            except GpuBusy as e:
                self.log_message("REFUSED %s model=%s: busy", self.path, model or "?")
                return self._json(503, {
                    "error": "The local GPU is busy with another job, so this answer "
                             "was refused rather than run on the CPU.",
                    "reason": "gpu_busy", "detail": str(e),
                    "model": model, "required_mib": req,
                })
            except InsufficientVram as e:
                self.log_message("REFUSED %s model=%s: %s", self.path, model or "?", e)
                return self._json(503, {
                    "error": "The local GPU does not have enough free memory for this "
                             "model, so this answer was refused rather than run on the CPU.",
                    "reason": "insufficient_vram", "detail": str(e),
                    "model": model, "required_mib": req, "free_mib": free_vram_mib(),
                })
            except Exception as e:
                return self._json(500, {"error": f"lease check failed: {e}",
                                        "reason": "probe_failed"})
        try:
            self._stream_upstream(body)
        finally:
            if fd is not None:
                os.close(fd)  # releases the flock

    def _stream_upstream(self, body: bytes):
        """Pass the upstream response through incrementally.

        Chunked, not buffered: local-rag's ollamaAnswer() reads NDJSON with
        getReader() and renders a growing answer, and buffering here would
        turn its live typing back into a spinner.
        """
        url = f"{UPSTREAM}{self.path}"
        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        req = urllib.request.Request(url, data=body or None, headers=headers,
                                     method=self.command)
        try:
            upstream = urllib.request.urlopen(req, timeout=900)
        except urllib.error.HTTPError as e:
            payload = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self._cors()
            self.end_headers()
            self.wfile.write(payload)
            return
        except Exception as e:
            return self._json(502, {"error": f"upstream unreachable: {e}",
                                    "reason": "upstream_unreachable"})
        with upstream:
            self.send_response(upstream.status)
            self.send_header("Content-Type",
                             upstream.headers.get("Content-Type", "application/json"))
            self.send_header("Transfer-Encoding", "chunked")
            self._cors()
            self.end_headers()
            try:
                while True:
                    buf = upstream.read(8192)
                    if not buf:
                        break
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(buf), buf))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                # Client navigated away or cancelled mid-answer. The finally in
                # _proxy still releases the lease, which is the part that matters.
                self.log_message("client disconnected mid-stream on %s", self.path)


def main():
    srv = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    srv.daemon_threads = True
    sys.stderr.write(
        f"[gate] listening on {LISTEN_HOST}:{LISTEN_PORT} -> {UPSTREAM}\n"
        f"[gate] lease={LOCK_PATH} keep_alive={KEEP_ALIVE!r}\n"
        f"[gate] required_mib={REQUIRED_MIB} fallback={FALLBACK_REQUIRED_MIB}\n"
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
