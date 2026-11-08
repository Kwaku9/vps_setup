# Kokoro TTS web page: type text, pick a Kokoro voice, hear it. CPU only.
# kokoro-onnx int8 model + voice pack baked in, pinned by sha256.
FROM docker.io/library/python:3.12-slim
ARG MODEL_URL=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
ARG MODEL_SHA=6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb
ARG VOICES_SHA=bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d
RUN pip install --no-cache-dir kokoro-onnx==0.4.7 fastapi==0.115.6 uvicorn==0.34.0 soundfile==0.13.1
ADD ${MODEL_URL}/kokoro-v1.0.int8.onnx /models/kokoro.onnx
ADD ${MODEL_URL}/voices-v1.0.bin /models/voices.bin
RUN echo "${MODEL_SHA}  /models/kokoro.onnx" | sha256sum -c - \
 && echo "${VOICES_SHA}  /models/voices.bin" | sha256sum -c - \
 && chmod 0444 /models/*
COPY server.py index.html /app/
WORKDIR /app
USER 65534:65534
EXPOSE 8881
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8881", "--workers", "1"]
