import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import jsonschema
import pytest

from app.config.settings import settings
from app.models.resource import ResourceState
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.factory import get_telemetry_provider
from app.services.telemetry.hybrid_provider import HybridTelemetryProvider
from app.services.telemetry.mock_provider import MockTelemetryProvider


# =========================================================================
# TEST FAKES (no HTTP, no Kubernetes cluster, no Prometheus server)
# =========================================================================

def build_kubernetes_state() -> ResourceState:
    """Fixed Kubernetes-shaped ResourceState as returned by KubernetesTelemetryProvider."""
    return ResourceState(
        event_id="11111111-1111-1111-1111-111111111111",
        trace_id="k8s-internal-trace",
        timestamp="2000-01-01T00:00:00+00:00",
        contract_version=settings.CONTRACT_VERSION,
        service_version=settings.SERVICE_VERSION,
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=0.0,
        memory_utilization=0.0,
        cpu_requested_cores=0.2,
        cpu_limit_cores=1.0,
        memory_requested_bytes=256 * 1024 * 1024,
        memory_limit_bytes=512 * 1024 * 1024,
        running_pods=2,
        desired_pods=3,
        pending_pods=1,
        request_rate=0.0,
        p95_latency_ms=0.0,
        error_rate=0.0,
        current_capacity_rps=700.0,
        estimated_required_capacity_rps=1.0,
        estimated_resource_waste=0.0,
    )


class FakeKubernetesProvider(ResourceTelemetryProvider):
    """Fake Kubernetes provider recording invocations; no external I/O."""

    @property
    def provider_name(self) -> str:
        return "kubernetes"

    def __init__(self, state: Optional[ResourceState] = None, error: Optional[TelemetryProviderError] = None):
        self.state = state if state is not None else build_kubernetes_state()
        self.error = error
        self.call_count = 0
        self.calls: List[Dict[str, Any]] = []

    async def fetch_resource_state(
        self,
        namespace: str = "sentinelscale",
        workload: str = "demo-api",
        trace_id: Optional[str] = None
    ) -> ResourceState:
        self.call_count += 1
        self.calls.append({"namespace": namespace, "workload": workload, "trace_id": trace_id})
        if self.error is not None:
            raise self.error
        return self.state


class FakePrometheusProvider(ResourceTelemetryProvider):
    """Fake Prometheus provider recording query invocations and concurrency."""

    @property
    def provider_name(self) -> str:
        return "prometheus"

    def __init__(
        self,
        request_rate: float = 350.0,
        p95_latency_ms: float = 42.5,
        error_rate: float = 0.02,
        cpu_utilization: float = 0.4,
        memory_utilization: float = 0.6,
        error: Optional[TelemetryProviderError] = None,
    ):
        self.request_rate = request_rate
        self.p95_latency_ms = p95_latency_ms
        self.error_rate = error_rate
        self.cpu_utilization = cpu_utilization
        self.memory_utilization = memory_utilization
        self.error = error
        self.operations: List[str] = []
        self.cpu_denominators: List[float] = []
        self.memory_denominators: List[int] = []
        self.current_in_flight = 0
        self.max_in_flight = 0

    async def fetch_resource_state(
        self,
        namespace: str = "sentinelscale",
        workload: str = "demo-api",
        trace_id: Optional[str] = None
    ) -> ResourceState:
        raise NotImplementedError(
            "FakePrometheusProvider exposes query methods only; the hybrid provider must not call fetch_resource_state on Prometheus."
        )

    async def _track(self, operation: str, value: float) -> float:
        self.operations.append(operation)
        self.current_in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.current_in_flight)
        await asyncio.sleep(0)  # yield to event loop to expose concurrency
        self.current_in_flight -= 1
        if self.error is not None:
            raise self.error
        return value

    async def query_request_rate(self, workload: str, trace_id: Optional[str] = None) -> float:
        return await self._track("query_request_rate", self.request_rate)

    async def query_p95_latency(self, workload: str, trace_id: Optional[str] = None) -> float:
        return await self._track("query_p95_latency", self.p95_latency_ms)

    async def query_error_rate(self, workload: str, trace_id: Optional[str] = None) -> float:
        return await self._track("query_error_rate", self.error_rate)

    async def query_cpu_utilization(
        self,
        workload: str,
        cpu_limit_cores: float,
        trace_id: Optional[str] = None
    ) -> float:
        self.cpu_denominators.append(cpu_limit_cores)
        return await self._track("query_cpu_utilization", self.cpu_utilization)

    async def query_memory_utilization(
        self,
        workload: str,
        memory_limit_bytes: int,
        trace_id: Optional[str] = None
    ) -> float:
        self.memory_denominators.append(memory_limit_bytes)
        return await self._track("query_memory_utilization", self.memory_utilization)


def build_hybrid(
    k8s_error: Optional[TelemetryProviderError] = None,
    prom_error: Optional[TelemetryProviderError] = None,
) -> tuple:
    k8s_fake = FakeKubernetesProvider(error=k8s_error)
    prom_fake = FakePrometheusProvider(error=prom_error)
    provider = HybridTelemetryProvider(
        kubernetes_provider=k8s_fake,
        prometheus_provider=prom_fake,
    )
    return provider, k8s_fake, prom_fake


def load_resource_state_schema() -> dict:
    schema_path = Path(__file__).resolve().parents[3] / "contracts" / "resources" / "resource_state.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


# =========================================================================
# INTERFACE & FACTORY
# =========================================================================

def test_hybrid_provider_implements_interface():
    """Verify HybridTelemetryProvider implements ResourceTelemetryProvider."""
    provider, _, _ = build_hybrid()
    assert isinstance(provider, ResourceTelemetryProvider)
    assert provider.provider_name == "hybrid"


def test_factory_resolves_hybrid_provider():
    """Verify factory resolves 'hybrid' and existing mappings remain intact."""
    provider = get_telemetry_provider("hybrid")
    assert isinstance(provider, HybridTelemetryProvider)
    assert provider.provider_name == "hybrid"

    # Existing behavior intact
    assert isinstance(get_telemetry_provider("mock"), MockTelemetryProvider)
    from app.services.telemetry.prometheus_provider import PrometheusTelemetryProvider
    from app.services.telemetry.kubernetes_provider import KubernetesTelemetryProvider
    assert isinstance(get_telemetry_provider("prometheus"), PrometheusTelemetryProvider)
    assert isinstance(get_telemetry_provider("kubernetes"), KubernetesTelemetryProvider)

    # Default provider behavior unchanged (mock)
    assert isinstance(get_telemetry_provider(), MockTelemetryProvider)


# =========================================================================
# COMPOSITION & MERGE BEHAVIOR
# =========================================================================

@pytest.mark.asyncio
async def test_both_providers_are_invoked():
    """Verify both Kubernetes and Prometheus providers are invoked with target context."""
    provider, k8s_fake, prom_fake = build_hybrid()

    state = await provider.fetch_resource_state(
        namespace="sentinelscale",
        workload="demo-api",
        trace_id="hybrid-trace-1"
    )

    assert k8s_fake.call_count == 1
    assert prom_fake.operations == [
        "query_request_rate",
        "query_p95_latency",
        "query_error_rate",
        "query_cpu_utilization",
        "query_memory_utilization",
    ]
    assert k8s_fake.calls[0]["namespace"] == "sentinelscale"
    assert k8s_fake.calls[0]["workload"] == "demo-api"
    assert k8s_fake.calls[0]["trace_id"] == "hybrid-trace-1"
    assert isinstance(state, ResourceState)


@pytest.mark.asyncio
async def test_kubernetes_telemetry_is_merged():
    """Verify Kubernetes infrastructure fields are merged into the final state."""
    provider, _, _ = build_hybrid()

    state = await provider.fetch_resource_state(trace_id="hybrid-trace-2")

    assert state.running_pods == 2
    assert state.desired_pods == 3
    assert state.pending_pods == 1
    assert state.cpu_requested_cores == 0.2
    assert state.cpu_limit_cores == 1.0
    assert state.memory_requested_bytes == 256 * 1024 * 1024
    assert state.memory_limit_bytes == 512 * 1024 * 1024


@pytest.mark.asyncio
async def test_prometheus_telemetry_is_merged():
    """Verify Prometheus runtime fields are merged into the final state."""
    provider, _, _ = build_hybrid()

    state = await provider.fetch_resource_state(trace_id="hybrid-trace-3")

    assert state.request_rate == 350.0
    assert state.p95_latency_ms == 42.5
    assert state.error_rate == 0.02
    assert state.cpu_utilization == 0.4
    assert state.memory_utilization == 0.6


@pytest.mark.asyncio
async def test_prometheus_utilization_uses_real_kubernetes_limits():
    """Verify Prometheus utilization queries receive real Kubernetes limits as denominators."""
    provider, _, prom_fake = build_hybrid()

    await provider.fetch_resource_state(trace_id="hybrid-trace-4")

    assert prom_fake.cpu_denominators == [1.0]
    assert prom_fake.memory_denominators == [512 * 1024 * 1024]


@pytest.mark.asyncio
async def test_derived_metrics_preserve_existing_formulas():
    """Verify derived metrics use the existing documented formulas with merged inputs."""
    provider, _, _ = build_hybrid()

    state = await provider.fetch_resource_state(trace_id="hybrid-trace-5")

    # Capacity: 2 running pods * 350 RPS = 700 RPS
    assert state.current_capacity_rps == 700.0
    # Required capacity: max(request_rate, 1.0) = 350.0
    assert state.estimated_required_capacity_rps == 350.0
    # Waste: (700 - 350) / 700 = 0.5
    assert state.estimated_resource_waste == 0.5


@pytest.mark.asyncio
async def test_output_is_valid_resource_state_conforming_to_contract():
    """Verify final output is a ResourceState conforming to the frozen JSON Schema contract."""
    provider, _, _ = build_hybrid()

    state = await provider.fetch_resource_state(
        namespace="sentinelscale",
        workload="demo-api",
        trace_id="hybrid-trace-6"
    )

    assert isinstance(state, ResourceState)
    jsonschema.validate(instance=state.model_dump(), schema=load_resource_state_schema())


# =========================================================================
# METADATA COHERENCE
# =========================================================================

@pytest.mark.asyncio
async def test_trace_id_is_propagated():
    """Verify the caller-supplied trace_id is propagated to the final state."""
    provider, k8s_fake, prom_fake = build_hybrid()

    state = await provider.fetch_resource_state(trace_id="hybrid-trace-7")

    assert state.trace_id == "hybrid-trace-7"
    assert k8s_fake.calls[0]["trace_id"] == "hybrid-trace-7"


@pytest.mark.asyncio
async def test_trace_id_generated_when_not_supplied():
    """Verify a trace-<hex> trace id is generated when none is supplied."""
    provider, _, _ = build_hybrid()

    state = await provider.fetch_resource_state()

    assert state.trace_id.startswith("trace-")


@pytest.mark.asyncio
async def test_final_metadata_is_coherent():
    """Verify one coherent metadata set: fresh event_id, single timestamp, correct versions."""
    provider, k8s_fake, _ = build_hybrid()
    k8s_state = k8s_fake.state

    state = await provider.fetch_resource_state(trace_id="hybrid-trace-8")

    # Fresh event_id (valid UUID, not leaked from the Kubernetes sub-state)
    assert state.event_id != k8s_state.event_id
    parsed_uuid = uuid.UUID(state.event_id)
    assert parsed_uuid.version == 4

    # Single fresh ISO-8601 timestamp (not the sub-state's stale timestamp)
    parsed_timestamp = datetime.fromisoformat(state.timestamp)
    assert parsed_timestamp.tzinfo is not None
    assert state.timestamp != k8s_state.timestamp

    # Versions and target context from configuration/arguments
    assert state.contract_version == settings.CONTRACT_VERSION
    assert state.service_version == settings.SERVICE_VERSION
    assert state.target_namespace == "sentinelscale"
    assert state.target_workload == "demo-api"


# =========================================================================
# FAILURE POLICY (no mock fallback, no fabricated telemetry)
# =========================================================================

@pytest.mark.asyncio
async def test_kubernetes_failure_raises_controlled_telemetry_error():
    """Verify Kubernetes provider failure becomes a controlled hybrid telemetry failure."""
    upstream_error = TelemetryProviderError(
        provider_name="kubernetes",
        message="Kubernetes API query timed out on get_deployment"
    )
    provider, _, prom_fake = build_hybrid(k8s_error=upstream_error)

    with pytest.raises(TelemetryProviderError) as exc_info:
        await provider.fetch_resource_state(trace_id="hybrid-trace-9")

    assert exc_info.value.provider_name == "hybrid"
    assert "Kubernetes telemetry failed" in str(exc_info.value)
    assert exc_info.value.original_error is upstream_error
    # Prometheus must not be consulted when Kubernetes already failed
    assert prom_fake.operations == []


@pytest.mark.asyncio
async def test_prometheus_failure_raises_controlled_telemetry_error():
    """Verify Prometheus provider failure becomes a controlled hybrid telemetry failure."""
    upstream_error = TelemetryProviderError(
        provider_name="prometheus",
        message="Prometheus HTTP 500 on query_request_rate"
    )
    provider, k8s_fake, _ = build_hybrid(prom_error=upstream_error)

    with pytest.raises(TelemetryProviderError) as exc_info:
        await provider.fetch_resource_state(trace_id="hybrid-trace-10")

    assert exc_info.value.provider_name == "hybrid"
    assert "Prometheus telemetry failed" in str(exc_info.value)
    assert exc_info.value.original_error is upstream_error
    # Kubernetes was invoked (it succeeds); failure came from Prometheus
    assert k8s_fake.call_count == 1


@pytest.mark.asyncio
async def test_no_mock_fallback_when_provider_fails():
    """Verify no fabricated ResourceState is returned when a real provider fails."""
    provider, _, _ = build_hybrid(
        prom_error=TelemetryProviderError(
            provider_name="prometheus",
            message="Failed to connect to Prometheus"
        )
    )

    with pytest.raises(TelemetryProviderError):
        await provider.fetch_resource_state(trace_id="hybrid-trace-11")

    # No mock fallback: the hybrid never consults MockTelemetryProvider
    mock_provider = MockTelemetryProvider()
    observer = ResourceObserverService(provider=provider)
    with pytest.raises(TelemetryProviderError):
        await observer.get_current_resource_state(trace_id="hybrid-trace-11")
    assert mock_provider.provider_name == "mock"  # mock remains available but unused


# =========================================================================
# CONCURRENCY
# =========================================================================

@pytest.mark.asyncio
async def test_prometheus_queries_execute_concurrently():
    """Verify independent Prometheus queries run concurrently via asyncio.gather."""
    provider, _, prom_fake = build_hybrid()

    await provider.fetch_resource_state(trace_id="hybrid-trace-12")

    # With gather, all 5 queries are in flight simultaneously; a sequential
    # implementation would never exceed 1.
    assert prom_fake.max_in_flight > 1


# =========================================================================
# OBSERVER INTEGRATION & EXISTING PROVIDER REGRESSION
# =========================================================================

@pytest.mark.asyncio
async def test_resource_observer_service_with_hybrid_provider():
    """Verify ResourceObserverService delegates seamlessly to the hybrid provider."""
    provider, _, _ = build_hybrid()
    observer = ResourceObserverService(provider=provider)

    state = await observer.get_current_resource_state(
        namespace="sentinelscale",
        workload="demo-api",
        trace_id="hybrid-trace-13"
    )

    assert isinstance(state, ResourceState)
    assert state.running_pods == 2
    assert state.request_rate == 350.0
    assert state.trace_id == "hybrid-trace-13"


@pytest.mark.asyncio
async def test_existing_mock_provider_continues_working():
    """Regression: existing MockTelemetryProvider behavior is unaffected by Phase 2B."""
    provider = MockTelemetryProvider()
    assert provider.provider_name == "mock"

    state = await provider.fetch_resource_state(
        namespace="sentinelscale",
        workload="demo-api",
        trace_id="mock-regression-trace"
    )

    assert isinstance(state, ResourceState)
    assert state.trace_id == "mock-regression-trace"
    assert state.running_pods >= 1