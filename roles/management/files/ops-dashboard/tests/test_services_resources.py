from unittest.mock import AsyncMock

import pytest

from ops_dashboard.api.dependencies import DashboardState, merge_live_containers
from ops_dashboard.api.routers.services import _service_to_schema
from ops_dashboard.api.schemas import MetricsSnapshot
from ops_dashboard.api.victoria import VictoriaMetricsClient
from ops_dashboard.models import EndpointType, Service, ServicePlatform
from ops_dashboard.providers.vps import VpsProvider


@pytest.mark.asyncio
async def test_discovered_containers_resolve_to_named_pods_and_refresh_membership():
    provider = VpsProvider()
    provider._ssh_command = AsyncMock(side_effect=[
        ('[{"Names":["loki"],"Pod":"abc123","PodName":"","State":"running"}]', 0),
        ('[{"Id":"abc123","Name":"logs-pod"}]', 0),
    ])
    state = DashboardState()
    merge_live_containers(state, await provider.list_containers())
    assert state.services["loki"].pod == "logs-pod"
    assert _service_to_schema(state, "loki").status == "running"
    merge_live_containers(state, [{"Names": ["loki"], "PodName": "new-logs-pod", "State": "exited"}])
    assert state.services["loki"].pod == "new-logs-pod"
    assert _service_to_schema(state, "loki").status == "stopped"


@pytest.mark.asyncio
async def test_pod_lookup_failure_keeps_containers_and_managed_config():
    provider = VpsProvider()
    provider._ssh_command = AsyncMock(side_effect=[
        ('[{"Names":["grafana"],"Pod":"abc123","State":"running"}]', 0), ('', 1),
    ])
    svc = Service("grafana", ServicePlatform.VPS, EndpointType.POD, pod="metrics-pod")
    state = DashboardState(services={"grafana": svc})
    merge_live_containers(state, await provider.list_containers())
    assert state.services["grafana"] is svc
    assert svc.pod == "metrics-pod"


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
