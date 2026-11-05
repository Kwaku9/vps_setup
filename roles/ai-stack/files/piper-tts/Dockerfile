# piper-tts: OpenAI-compatible TTS (Piper, CPU/ONNX) in kokoro-tts's place. ~0.4 GB vs kokoro's 5.7 GB (PyTorch).
# Built on python:3.12-slim, already on the box for other services, so its layers are shared.
FROM docker.io/library/python:3.12-slim
RUN pip install --no-cache-dir piper-tts==1.8.0 lameenc==1.9.0
# The voice is baked in at build time (pinned to the piper-voices v1.0.0 tag), so the container needs no egress.
ARG VOICE=en_US-amy-medium
ARG VOICE_BASE=https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium
RUN mkdir /voices && python3 -c "import urllib.request as u; [u.urlretrieve('${VOICE_BASE}/${VOICE}' + s, '/voices/${VOICE}' + s) for s in ('.onnx', '.onnx.json')]" \
    && python3 -c "import os; assert os.path.getsize('/voices/${VOICE}.onnx') > 10_000_000, 'voice download truncated'"
COPY server.py /app/server.py
ENV PIPER_VOICE_PATH=/voices/${VOICE}.onnx PORT=8880 PYTHONUNBUFFERED=1
USER nobody
EXPOSE 8880
CMD ["python3", "/app/server.py"]
