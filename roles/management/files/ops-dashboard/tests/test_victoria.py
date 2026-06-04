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
        # This branch matches the compound percent expression (usage/limit binary op).
        if "podman_container_mem_usage_bytes" in promql and "podman_container_mem_limit_bytes" in promql:
            # The PromQL expression for the percentage; mocked to return 50.0 directly
            return [{"metric": {"name": "svc-a"}, "value": ["1700000000", "50.0"]}]
        if "podman_container_mem_usage_bytes" in promql:
            return [{"metric": {"name": "svc-a"}, "value": ["1700000000", "52428800"]}]  # 50MB
        # podman_container_mem_percent must NEVER be queried — that's the bug we fixed
        if "podman_container_mem_percent" in promql:
            pytest.fail("Client must not query podman_container_mem_percent — it does not exist")
        return []

    client.query = fake_query  # type: ignore[method-assign]
    snapshots = await client.query_all_containers()

    assert "svc-a" in snapshots
    assert snapshots["svc-a"].memory_percent == pytest.approx(50.0)
    assert snapshots["svc-a"].cpu_percent == pytest.approx(12.5)
    assert snapshots["svc-a"].memory_usage_mb == pytest.approx(50.0)
    assert snapshots["svc-a"].status == "running"


@pytest.mark.asyncio
async def test_query_range_returns_typed_tuples():
    """query_range mocks the httpx call directly and confirms the return shape."""
    import httpx

    client = VictoriaMetricsClient(base_url="http://example.invalid")

    class _FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {
                "data": {
                    "result": [
                        {"metric": {"name": "svc-a"}, "values": [
                            ["1700000000", "12.5"],
                            ["1700000030", "13.0"],
                        ]}
                    ]
                }
            }

    class _FakeClient:
        is_closed = False
        async def get(self, *a, **kw): return _FakeResp()

    client._client = _FakeClient()  # type: ignore[assignment]
    points = await client.query_range("any_promql", minutes=15)
    assert points == [(1700000000.0, 12.5), (1700000030.0, 13.0)]
    assert all(isinstance(p, tuple) and len(p) == 2 for p in points)


@pytest.mark.asyncio
async def test_query_range_empty_result_returns_empty_list():
    client = VictoriaMetricsClient(base_url="http://example.invalid")

    class _FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"data": {"result": []}}

    class _FakeClient:
        is_closed = False
        async def get(self, *a, **kw): return _FakeResp()

    client._client = _FakeClient()  # type: ignore[assignment]
    assert await client.query_range("any_promql", minutes=15) == []
