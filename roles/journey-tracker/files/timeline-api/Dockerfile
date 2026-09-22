FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
ENV API_PORT=8080
# Loopback only. The container runs INSIDE frontend-pod, sharing its network
# namespace with the journey-tracker nginx, which proxies /api/ to 127.0.0.1:8080.
# No host port is published and nothing outside the pod can reach it.
CMD ["sh", "-c", "uvicorn main:app --host 127.0.0.1 --port ${API_PORT} --workers 1 --no-access-log"]
