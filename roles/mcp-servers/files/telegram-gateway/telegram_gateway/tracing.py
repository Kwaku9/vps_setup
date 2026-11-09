import logging
import time

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

from telegram_gateway.config import OTEL_EXPORTER_OTLP_ENDPOINT

OTLP_EXPORTER_LOGGER = "opentelemetry.exporter.otlp.proto.http.trace_exporter"


class ThrottleExportFailures(logging.Filter):
    """Collapse OTLP exporter failure spam to one WARNING per interval.

    The collector (Alloy in logs-pod) is stopped by the nightly 06:00 vps-backup
    for ~15 min. While it is gone podman DNS has no record for `logs-pod`, so
    every span batch logs several "Transient error ... Failed to resolve
    'logs-pod'" WARNINGs and then a "Failed to export span batch" ERROR —
    ~230 lines a night from this container alone. The endpoint is correct;
    the spans in that window are simply lost. Let one record per interval
    through (as WARNING, with a count of what was dropped) so a real,
    persistent misconfiguration still shows up.
    """

    def __init__(self, interval_seconds: float = 600.0, clock=time.monotonic):
        super().__init__()
        self.interval = interval_seconds
        self._clock = clock
        self._last: float | None = None
        self._suppressed = 0

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING:
            return True
        now = self._clock()
        if self._last is not None and now - self._last < self.interval:
            self._suppressed += 1
            return False
        if record.levelno > logging.WARNING:
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
        if self._suppressed:
            record.msg = "%s (%d similar OTLP export message(s) suppressed)" % (
                record.getMessage(), self._suppressed)
            record.args = ()
        self._last = now
        self._suppressed = 0
        return True


def init_tracing(app):
    resource = Resource.create({"service.name": "telegram-gateway"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=f"{OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces"
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    exporter_logger = logging.getLogger(OTLP_EXPORTER_LOGGER)
    if not any(isinstance(f, ThrottleExportFailures) for f in exporter_logger.filters):
        exporter_logger.addFilter(ThrottleExportFailures())

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    AsyncPGInstrumentor().instrument()

    return provider
