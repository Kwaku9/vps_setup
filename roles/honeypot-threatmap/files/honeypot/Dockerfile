FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn[standard] maxminddb prometheus-client
COPY honeypot.py .
EXPOSE 8099
CMD ["uvicorn", "honeypot:app", "--host", "0.0.0.0", "--port", "8099", "--workers", "2", "--access-log"]
