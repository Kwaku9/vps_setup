"""Regression test: memory_percent must be computed, not pulled from a non-existent metric."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from ops_dashboard.api.victoria import VictoriaMetricsClient


@pytest.mark.asyncio
async def test_memory_percent_computed_from_usage_and_limit():
    """Memory percent is calculated from mem_usage_bytes/mem_limit_bytes,
    NOT pulled from podman_container_mem_percent (which doesn't exist)."""
    client = VictoriaMetricsClient(base_url="http://example.invalid")

    # Mock the query method — return a state row + usage 50MB + limit 100MB for "svc-a"
    async def fake_query(promql: str):
        if "podman_container_state" in promql:
            return [{"metric": {"name": "svc-a"}, "value": ["1700000000", "2"]}]
        if "podman_container_cpu_percent" in promql:
            return [{"metric": {"name": "svc-a"}, "value": ["1700000000", "12.5"]}]
        # The fix: client must compute percent from these two metrics
        if "podman_container_mem_usage_bytes" in promql and "podman_container_mem_limit_bytes" in promql:
            # The PromQL expression for the percentage; mocked to return 50.0 directly
            return [{"metric": {"name": "svc-a"}, "value": ["1700000000", "50.0"]}]
        if "podman_container_mem_usage_bytes" in promql:
            return [{"metric": {"name": "svc-a"}, "value": ["1700000000", "52428800"]}]  # 50MB
        # podman_container_mem_percent must NEVER be queried — that's the bug we fixed
        if promql.strip() == "podman_container_mem_percent":
            pytest.fail("Client must not query podman_container_mem_percent — it does not exist")
        return []

    client.query = fake_query  # type: ignore[method-assign]
    snapshots = await client.query_all_containers()

    assert "svc-a" in snapshots
    assert snapshots["svc-a"].memory_percent == pytest.approx(50.0)
    assert snapshots["svc-a"].cpu_percent == pytest.approx(12.5)
    assert snapshots["svc-a"].memory_usage_mb == pytest.approx(50.0)
    assert snapshots["svc-a"].status == "running"
