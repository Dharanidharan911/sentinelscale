import asyncio
import json
import pytest
import httpx
from fastapi.testclient import TestClient
from app.clients.demand_client import DemandIntelligenceClient, UpstreamDemandIntelligenceError
from app.clients.traffic_client import TrafficIntelligenceClient, UpstreamTrafficIntelligenceError
from app.main import app
from app.models.context import DecisionContext, PolicyOverrides
from app.models.decision import ScalingAction, ScalingDecision
from app.models.demand_contract import DemandForecast
from app.models.resource import ResourceState
from app.models.traffic_contract import TrafficAssessment, TrafficClassification
from app.services.context_aggregator import AggregationError, ContextAggregatorService
from app.services.decision_engine import DecisionEngine
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.base import TelemetryProviderError
from app.services.telemetry.mock_provider import MockTelemetryProvider


def make_valid_traffic_assessment(trace_id="test-trace-123"):
    return TrafficAssessment(
        event_id="traffic-evt-001",
        trace_id=trace_id,
        timestamp="2026-09-03T18:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="traffic-rules-v1",
        window_seconds=60,
        total_rps=2500.0,
        legitimate_rps_estimate=850.0,
        suspicious_rps_estimate=1650.0,
        risk_score=0.84,
        legitimacy_score=0.34,
        confidence=0.91,
        classification=TrafficClassification.SUSPICIOUS,
        top_signals=["high_burst_rate", "client_ip_concentration"],
    )


def make_valid_demand_forecast(trace_id="test-trace-123"):
    return DemandForecast(
        event_id="demand-evt-001",
        trace_id=trace_id,
        generated_at="2026-09-03T18:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="demand-v0",
        forecast_horizon_seconds=300,
        predicted_legitimate_rps=1200.0,
        lower_bound_rps=1050.0,
        upper_bound_rps=1400.0,
        confidence=0.91,
    )


def make_valid_resource_state(trace_id="test-trace-123"):
    return ResourceState(
        event_id="res-evt-001",
        trace_id=trace_id,
        timestamp="2026-09-03T18:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=0.68,
        memory_utilization=0.52,
        cpu_requested_cores=4.0,
        cpu_limit_cores=8.0,
        memory_requested_bytes=4294967296,
        memory_limit_bytes=8589934592,
        running_pods=4,
        desired_pods=4,
        pending_pods=0,
        request_rate=2500.0,
        p95_latency_ms=42.5,
        error_rate=0.002,
        current_capacity_rps=1400.0,
        estimated_required_capacity_rps=1200.0,
        estimated_resource_waste=0.14,
    )


# ==============================================================================
# 1. Successful Aggregation & Full Orchestration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_successful_context_aggregation():
    """Test concurrent collection and canonical DecisionContext construction."""
    trace_id = "trace-agg-success-01"

    # Mock Traffic Client
    def traffic_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Trace-ID") == trace_id
        return httpx.Response(200, json=make_valid_traffic_assessment(trace_id).model_dump())

    # Mock Demand Client
    def demand_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Trace-ID") == trace_id
        return httpx.Response(200, json=make_valid_demand_forecast(trace_id).model_dump())

    traffic_client = TrafficIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(traffic_handler))
    )
    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(demand_handler))
    )
    resource_observer = ResourceObserverService(provider=MockTelemetryProvider())

    aggregator = ContextAggregatorService(
        traffic_client=traffic_client,
        demand_client=demand_client,
        resource_observer=resource_observer,
        decision_engine=DecisionEngine(),
    )

    context = await aggregator.aggregate_context(
        namespace="sentinelscale",
        workload="demo-api",
        window_seconds=60,
        forecast_horizon_seconds=300,
        trace_id=trace_id,
    )

    assert isinstance(context, DecisionContext)
    assert context.trace_id == trace_id
    assert context.target_workload == "demo-api"
    assert context.traffic_assessment.risk_score == 0.84
    assert context.demand_forecast.predicted_legitimate_rps == 1200.0
    assert context.resource_state.running_pods == 4
    assert context.dry_run is True
    assert context.shadow_mode is True


@pytest.mark.asyncio
async def test_successful_decision_orchestration():
    """Test full end-to-end orchestration returning deterministic ScalingDecision."""
    trace_id = "trace-orch-success-02"

    def traffic_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_valid_traffic_assessment(trace_id).model_dump())

    def demand_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_valid_demand_forecast(trace_id).model_dump())

    traffic_client = TrafficIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(traffic_handler))
    )
    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(demand_handler))
    )
    aggregator = ContextAggregatorService(
        traffic_client=traffic_client,
        demand_client=demand_client,
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
        decision_engine=DecisionEngine(),
    )

    decision = await aggregator.orchestrate_decision(
        namespace="sentinelscale",
        workload="demo-api",
        trace_id=trace_id,
    )

    assert isinstance(decision, ScalingDecision)
    assert decision.trace_id == trace_id
    assert decision.action == ScalingAction.HOLD
    assert decision.recommended_pods == 4
    assert decision.dry_run is True
    assert decision.shadow_mode is True


# ==============================================================================
# 2. Failure Handling Tests (Explicit failures, zero fabricated data)
# ==============================================================================

@pytest.mark.asyncio
async def test_traffic_intelligence_http_500_raises_aggregation_error():
    """Verify that Traffic Intelligence failure raises controlled AggregationError."""
    def traffic_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error in Traffic Intelligence")

    def demand_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_valid_demand_forecast().model_dump())

    traffic_client = TrafficIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(traffic_handler))
    )
    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(demand_handler))
    )
    aggregator = ContextAggregatorService(
        traffic_client=traffic_client,
        demand_client=demand_client,
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
    )

    with pytest.raises(AggregationError) as exc_info:
        await aggregator.aggregate_context(trace_id="test-trace-fail-1")

    assert exc_info.value.source == "Traffic Intelligence"
    assert "HTTP 500" in exc_info.value.message


@pytest.mark.asyncio
async def test_demand_intelligence_timeout_raises_aggregation_error():
    """Verify that Demand Intelligence timeout raises controlled AggregationError."""
    def traffic_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_valid_traffic_assessment().model_dump())

    def demand_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Connection timed out")

    traffic_client = TrafficIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(traffic_handler))
    )
    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(demand_handler))
    )
    aggregator = ContextAggregatorService(
        traffic_client=traffic_client,
        demand_client=demand_client,
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
    )

    with pytest.raises(AggregationError) as exc_info:
        await aggregator.aggregate_context(trace_id="test-trace-fail-2")

    assert exc_info.value.source == "Demand Intelligence"
    assert "timed out" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_resource_intelligence_failure_raises_aggregation_error():
    """Verify that Resource Observer failure raises controlled AggregationError."""
    def traffic_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_valid_traffic_assessment().model_dump())

    def demand_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_valid_demand_forecast().model_dump())

    traffic_client = TrafficIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(traffic_handler))
    )
    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(demand_handler))
    )
    failing_observer = ResourceObserverService(
        provider=MockTelemetryProvider(should_fail=True, failure_message="Prometheus cluster unreachable")
    )

    aggregator = ContextAggregatorService(
        traffic_client=traffic_client,
        demand_client=demand_client,
        resource_observer=failing_observer,
    )

    with pytest.raises(AggregationError) as exc_info:
        await aggregator.aggregate_context(trace_id="test-trace-fail-3")

    assert exc_info.value.source == "Resource Intelligence"
    assert "Prometheus cluster unreachable" in exc_info.value.message


@pytest.mark.asyncio
async def test_invalid_traffic_schema_raises_aggregation_error():
    """Verify that malformed Traffic payload raises contract validation error."""
    def traffic_handler(request: httpx.Request) -> httpx.Response:
        # Missing required total_rps and risk_score
        return httpx.Response(200, json={"event_id": "123", "classification": "invalid_enum"})

    def demand_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_valid_demand_forecast().model_dump())

    traffic_client = TrafficIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(traffic_handler))
    )
    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(demand_handler))
    )
    aggregator = ContextAggregatorService(
        traffic_client=traffic_client,
        demand_client=demand_client,
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
    )

    with pytest.raises(AggregationError) as exc_info:
        await aggregator.aggregate_context(trace_id="test-trace-fail-4")

    assert exc_info.value.source == "Traffic Intelligence"
    assert "contract validation failed" in exc_info.value.message


# ==============================================================================
# 3. Trace ID & Metadata Propagation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_trace_id_propagation_and_auto_generation():
    """Verify that custom trace_id is propagated or auto-generated consistently."""
    captured_traces = {}

    def traffic_handler(request: httpx.Request) -> httpx.Response:
        t_id = request.headers.get("X-Trace-ID")
        captured_traces["traffic"] = t_id
        return httpx.Response(200, json=make_valid_traffic_assessment(t_id).model_dump())

    def demand_handler(request: httpx.Request) -> httpx.Response:
        t_id = request.headers.get("X-Trace-ID")
        captured_traces["demand"] = t_id
        return httpx.Response(200, json=make_valid_demand_forecast(t_id).model_dump())

    traffic_client = TrafficIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(traffic_handler))
    )
    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(demand_handler))
    )
    aggregator = ContextAggregatorService(
        traffic_client=traffic_client,
        demand_client=demand_client,
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
    )

    # 1. With explicit trace_id
    ctx1 = await aggregator.aggregate_context(trace_id="custom-trace-999")
    assert ctx1.trace_id == "custom-trace-999"
    assert captured_traces["traffic"] == "custom-trace-999"
    assert captured_traces["demand"] == "custom-trace-999"

    # 2. Without explicit trace_id (auto-generated)
    ctx2 = await aggregator.aggregate_context(trace_id=None)
    assert ctx2.trace_id.startswith("trace-")
    assert captured_traces["traffic"] == ctx2.trace_id
    assert captured_traces["demand"] == ctx2.trace_id


@pytest.mark.asyncio
async def test_policy_overrides_propagation():
    """Verify that policy overrides propagate through aggregation into DecisionEngine."""
    def traffic_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_valid_traffic_assessment().model_dump())

    def demand_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_valid_demand_forecast().model_dump())

    aggregator = ContextAggregatorService(
        traffic_client=TrafficIntelligenceClient(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(traffic_handler))
        ),
        demand_client=DemandIntelligenceClient(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(demand_handler))
        ),
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
        decision_engine=DecisionEngine(),
    )

    overrides = PolicyOverrides(min_pods=5, max_pods=15)
    decision = await aggregator.orchestrate_decision(policy_overrides=overrides)

    assert decision.recommended_pods >= 5


# ==============================================================================
# 4. API Route Integration Tests
# ==============================================================================

client = TestClient(app)


def test_api_orchestrate_endpoint_success(monkeypatch):
    """Test POST /api/v1/decision/orchestrate endpoint."""
    async def mock_orchestrate(self, **kwargs):
        return ScalingDecision(
            decision_id="dec-api-01",
            event_id="evt-api-01",
            trace_id=kwargs.get("trace_id") or "trace-api-01",
            timestamp="2026-09-03T18:00:00Z",
            contract_version="1.0.0",
            service_version="0.1.0",
            model_version="policy-rules-v0",
            action=ScalingAction.HOLD,
            reason="Holding under test mock",
            confidence=0.91,
            traffic_risk=0.84,
            predicted_legitimate_rps=1200.0,
            current_capacity_rps=1400.0,
            current_pods=4,
            recommended_pods=4,
            baseline_hpa_recommended_pods=8,
            pod_delta_vs_baseline=-4,
            policy="default-safe-guardrail-v1",
            dry_run=True,
            shadow_mode=True,
        )

    monkeypatch.setattr(ContextAggregatorService, "orchestrate_decision", mock_orchestrate)

    response = client.post(
        "/api/v1/decision/orchestrate",
        json={"namespace": "sentinelscale", "workload": "demo-api", "window_seconds": 60},
        headers={"X-Trace-ID": "trace-api-header-123"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["decision_id"] == "dec-api-01"
    assert data["action"] == "HOLD"
    assert data["dry_run"] is True


def test_api_aggregate_endpoint_success(monkeypatch):
    """Test POST /api/v1/decision/aggregate endpoint returning DecisionContext."""
    async def mock_aggregate(self, **kwargs):
        return DecisionContext(
            context_id="ctx-api-01",
            trace_id=kwargs.get("trace_id") or "trace-api-01",
            timestamp="2026-09-03T18:00:00Z",
            contract_version="1.0.0",
            target_workload=kwargs.get("workload") or "demo-api",
            traffic_assessment=make_valid_traffic_assessment(),
            demand_forecast=make_valid_demand_forecast(),
            resource_state=make_valid_resource_state(),
            dry_run=True,
            shadow_mode=True,
        )

    monkeypatch.setattr(ContextAggregatorService, "aggregate_context", mock_aggregate)

    response = client.post(
        "/api/v1/decision/aggregate",
        json={"namespace": "sentinelscale", "workload": "demo-api"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["context_id"] == "ctx-api-01"
    assert "traffic_assessment" in data
    assert "demand_forecast" in data
    assert "resource_state" in data


def test_api_orchestrate_upstream_failure_returns_502(monkeypatch):
    """Test that AggregationError surfaces as HTTP 502 Bad Gateway."""
    async def mock_orchestrate_fail(self, **kwargs):
        raise AggregationError(
            source="Traffic Intelligence",
            message="Connection refused to traffic-intelligence:8001",
        )

    monkeypatch.setattr(ContextAggregatorService, "orchestrate_decision", mock_orchestrate_fail)

    response = client.post("/api/v1/decision/orchestrate", json={})
    assert response.status_code == 502
    assert "Decision Orchestration Failure: [Traffic Intelligence]" in response.json()["detail"]

