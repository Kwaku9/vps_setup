FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx aiofiles maxminddb
COPY server.py .
COPY static/ static/
EXPOSE 8097
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8097"]
