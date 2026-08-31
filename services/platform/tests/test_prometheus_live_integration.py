import httpx
import pytest
from app.config.settings import settings
from app.models.resource import ResourceState
from app.services.telemetry.prometheus_provider import PrometheusTelemetryProvider


@pytest.mark.asyncio
async def test_live_prometheus_integration_optional():
    """
    Live Integration Test against running Prometheus instance.
    Automatically skipped if Prometheus is not running locally.
    """
    target_url = "http://localhost:9090"
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(f"{target_url}/-/healthy")
            if resp.status_code != 200:
                pytest.skip("Local Prometheus server is not responding at http://localhost:9090")
    except Exception:
        pytest.skip("Local Prometheus server is unreachable at http://localhost:9090 (Integration test skipped)")

    provider = PrometheusTelemetryProvider(base_url=target_url)
    state = await provider.fetch_resource_state(namespace="sentinelscale", workload="demo-api")

    assert isinstance(state, ResourceState)
    assert state.target_workload == "demo-api"
    assert state.current_capacity_rps > 0.0

