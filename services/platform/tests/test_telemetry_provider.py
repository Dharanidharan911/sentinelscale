import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.resource import ResourceState
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.factory import get_telemetry_provider
from app.services.telemetry.mock_provider import MockTelemetryProvider
from app.api.v1.endpoints import get_telemetry_provider as endpoint_get_provider


def test_resource_telemetry_provider_is_abstract():
    """Verify ResourceTelemetryProvider interface cannot be instantiated directly."""
    with pytest.raises(TypeError):
        ResourceTelemetryProvider()


@pytest.mark.asyncio
async def test_mock_telemetry_provider_returns_valid_resource_state():
    """Verify MockTelemetryProvider produces a valid, schema-compliant ResourceState."""
    provider = MockTelemetryProvider()
    assert provider.provider_name == "mock"

    state = await provider.fetch_resource_state(
        namespace="sentinelscale",
        workload="demo-api",
        trace_id="test-trace-provider-1"
    )

    assert isinstance(state, ResourceState)
    assert state.target_namespace == "sentinelscale"
    assert state.target_workload == "demo-api"
    assert state.trace_id == "test-trace-provider-1"
    assert state.running_pods >= 1
    assert state.cpu_utilization >= 0.0
    assert state.current_capacity_rps > 0.0


@pytest.mark.asyncio
async def test_resource_observer_service_with_injected_provider():
    """Verify ResourceObserverService delegates correctly to injected provider."""
    mock_provider = MockTelemetryProvider()
    observer = ResourceObserverService(provider=mock_provider)

    state = await observer.get_current_resource_state(
        namespace="test-ns",
        workload="test-app"
    )

    assert isinstance(state, ResourceState)
    assert state.target_namespace == "test-ns"
    assert state.target_workload == "test-app"


@pytest.mark.asyncio
async def test_mock_telemetry_provider_explicit_failure_behavior():
    """Verify MockTelemetryProvider explicitly raises TelemetryProviderError when failing."""
    failing_provider = MockTelemetryProvider(
        should_fail=True,
        failure_message="Connection to metrics backend timed out"
    )
    assert failing_provider.provider_name == "mock"

    with pytest.raises(TelemetryProviderError) as exc_info:
        await failing_provider.fetch_resource_state(
            namespace="sentinelscale",
            workload="demo-api"
        )

    assert exc_info.value.provider_name == "mock"
    assert "Connection to metrics backend timed out" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resource_observer_propagates_provider_failure():
    """Verify ResourceObserver does not silently swallow or fake telemetry on provider failure."""
    failing_provider = MockTelemetryProvider(
        should_fail=True,
        failure_message="Cluster unreachable"
    )
    observer = ResourceObserverService(provider=failing_provider)

    with pytest.raises(TelemetryProviderError) as exc_info:
        await observer.get_current_resource_state(
            namespace="sentinelscale",
            workload="demo-api"
        )

    assert "Cluster unreachable" in str(exc_info.value)


def test_telemetry_provider_factory():
    """Verify factory returns appropriate provider and handles invalid / future choices."""
    # 1. Mock provider
    provider = get_telemetry_provider("mock")
    assert isinstance(provider, MockTelemetryProvider)

    # 2. Future providers raise NotImplementedError
    with pytest.raises(NotImplementedError):
        get_telemetry_provider("prometheus")

    with pytest.raises(NotImplementedError):
        get_telemetry_provider("kubernetes")

    # 3. Unknown provider raises TelemetryProviderError
    with pytest.raises(TelemetryProviderError):
        get_telemetry_provider("non_existent_provider")


def test_api_endpoint_surfaces_provider_failure_as_502():
    """Verify /api/v1/resources/current returns 502 Bad Gateway when provider fails."""
    client = TestClient(app)

    # Override dependency with a failing provider
    def failing_provider_override():
        return MockTelemetryProvider(should_fail=True, failure_message="Prometheus connection refused")

    app.dependency_overrides[endpoint_get_provider] = failing_provider_override
    try:
        response = client.get("/api/v1/resources/current?namespace=sentinelscale&workload=demo-api")
        assert response.status_code == 502
        data = response.json()
        assert "Telemetry Provider Failure" in data["detail"]
    finally:
        app.dependency_overrides.clear()

