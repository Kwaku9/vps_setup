from unittest.mock import AsyncMock

import pytest

from ops_dashboard.api.dependencies import DashboardState
from ops_dashboard.api.routers.services import _service_to_schema
from ops_dashboard.api.schemas import MetricsSnapshot
from ops_dashboard.api.victoria import VictoriaMetricsClient
from ops_dashboard.models import EndpointType, Service, ServicePlatform


@pytest.mark.asyncio
async def test_missing_or_invalid_metrics_are_unknown_instead_of_healthy_zeroes():
    client = VictoriaMetricsClient()
    client.query = AsyncMock(side_effect=[
        [{"metric": {"name": "svc"}, "value": [0, "2"]}],
        RuntimeError("CPU scrape unavailable"),
        [{"metric": {"name": "svc"}, "value": [0, "+Inf"]}],
        [{"metric": {"name": "svc"}, "value": [0, "104857600"]}],
        [{"metric": {"name": "svc"}, "value": [0, "100"]}],
    ])
    samples = await client.query_all_containers()
    assert samples["svc"].cpu_percent is None
    assert samples["svc"].memory_percent is None
    assert samples["svc"].memory_usage_mb == 100
    assert samples["svc"].status == "running"
    assert samples["svc"].timestamp == 100  # scrape time, not the time of the HTTP query


def test_service_response_exposes_actual_memory_and_metric_age():
    svc = Service("svc", ServicePlatform.VPS, EndpointType.POD, memory_mb=4096)
    state = DashboardState(services={"svc": svc}, metrics_cache={"svc": MetricsSnapshot(
        service_name="svc", timestamp=100, status="running", memory_usage_mb=123.4,
    )})
    result = _service_to_schema(state, "svc")
    assert result.memory_usage_mb == 123.4  # actual usage, not the configured limit
    assert result.metrics_at == 100
    assert result.cpu_percent is None
