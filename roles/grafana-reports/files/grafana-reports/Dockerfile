FROM python:3.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev

COPY grafana_reports/ ./grafana_reports/
ENV PYTHONPATH=/app
ENV LOCAL_DIR=/app/renders

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/healthz')" || exit 1

CMD ["uv", "run", "--", "python", "-m", "grafana_reports.main"]
