# Kokoro TTS web page: type text, pick a Kokoro voice, hear it. CPU only.
# kokoro-onnx int8 model + voice pack baked in (sha256 pinned in kokoro-web.yml).
FROM docker.io/library/python:3.12-slim
# Model + voice pack are fetched by Ansible (get_url, pinned sha256, retries)
# into models/ next to this file; the build only copies them, so it no longer
# depends on GitHub's CDN (it returned 504 mid-build on 2026-11-09).
RUN pip install --no-cache-dir kokoro-onnx==0.4.7 fastapi==0.115.6 uvicorn==0.34.0 soundfile==0.13.1
COPY models/kokoro.onnx models/voices.bin /models/
COPY server.py index.html /app/
WORKDIR /app
# Return freed memory to the OS instead of holding it (glibc keeps freed heap
# by default; Kokoro held ~900 MB after one long request).
ENV MALLOC_ARENA_MAX=2 MALLOC_TRIM_THRESHOLD_=131072 OMP_NUM_THREADS=2
USER 65534:65534
EXPOSE 8881
# Recycle the worker after 40 requests: memory creeps ~40 MB per long request
# (allocator fragmentation); the process exits cleanly between requests and the
# container restart policy starts a fresh one.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8881", "--workers", "1", "--limit-max-requests", "40"]
