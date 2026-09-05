import json
import os
import time
from datetime import datetime, timezone
import pytest
import httpx
from pydantic import ValidationError

from app.clients.demand_client import DemandIntelligenceClient, UpstreamDemandIntelligenceError
from app.clients.traffic_client import TrafficIntelligenceClient
from app.models.context import DecisionContext
from app.models.decision import ScalingAction, ScalingDecision
from app.models.demand_contract import DemandForecast, DemandObservation
from app.models.resource import ResourceState
from app.models.traffic_contract import TrafficAssessment, TrafficClassification
from app.services.context_aggregator import AggregationError, ContextAggregatorService
from app.services.decision_engine import DecisionEngine
from app.services.history.demand_accumulator import DemandObservationAccumulator
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.mock_provider import MockTelemetryProvider


# ==============================================================================
# Fixtures and Helpers
# ==============================================================================

def make_traffic_assessment(
    total_rps: float = 800.0,
    legitimate_rps: float = 750.0,
    risk_score: float = 0.10,
    legitimacy_score: float = 0.90,
    confidence: float = 0.95,
    classification: TrafficClassification = TrafficClassification.LEGITIMATE,
    trace_id: str = "trace-f3-test",
    timestamp: str | None = None,
) -> TrafficAssessment:
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    return TrafficAssessment(
        event_id=f"evt-tr-{int(time.time()*1000)}-{os.urandom(4).hex()}",
        trace_id=trace_id,
        timestamp=ts,
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="traffic-rules-v1",
        window_seconds=60,
        total_rps=total_rps,
        legitimate_rps_estimate=legitimate_rps,
        suspicious_rps_estimate=total_rps - legitimate_rps,
        risk_score=risk_score,
        legitimacy_score=legitimacy_score,
        confidence=confidence,
        classification=classification,
        top_signals=[],
    )


def make_demand_forecast(
    predicted_rps: float = 820.0,
    confidence: float = 0.92,
    trace_id: str = "trace-f3-test",
) -> DemandForecast:
    return DemandForecast(
        event_id=f"evt-dm-{int(time.time()*1000)}-{os.urandom(4).hex()}",
        trace_id=trace_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="demand-v1",
        forecast_horizon_seconds=300,
        predicted_legitimate_rps=predicted_rps,
        lower_bound_rps=predicted_rps * 0.90,
        upper_bound_rps=predicted_rps * 1.10,
        confidence=confidence,
    )


def make_resource_state(trace_id: str = "trace-f3-test") -> ResourceState:
    return ResourceState(
        event_id="res-evt-f3",
        trace_id=trace_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        contract_version="1.0.0",
        service_version="0.1.0",
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=0.55,
        memory_utilization=0.48,
        cpu_requested_cores=4.0,
        cpu_limit_cores=8.0,
        memory_requested_bytes=4294967296,
        memory_limit_bytes=8589934592,
        running_pods=4,
        desired_pods=4,
        pending_pods=0,
        request_rate=800.0,
        p95_latency_ms=35.0,
        error_rate=0.001,
        current_capacity_rps=1400.0,
        estimated_required_capacity_rps=800.0,
        estimated_resource_waste=0.42,
    )


# ==============================================================================
# 1. Retrieval and Forwarding of F2 Observations
# ==============================================================================

@pytest.mark.asyncio
async def test_f2_observations_retrieved_and_passed_to_m2(tmp_path):
    """Verify that accumulated historical observations are retrieved from SQLite and sent to M2."""
    db_path = str(tmp_path / "test_f3_accumulator.db")
    accumulator = DemandObservationAccumulator(db_path=db_path)

    # Seed 3 historical legitimate observations relative to now
    now = time.time()
    for i in range(3):
        ts_iso = datetime.fromtimestamp(now - 180 + i * 60, tz=timezone.utc).isoformat()
        ass = make_traffic_assessment(
            total_rps=500.0 + i * 50.0,
            legitimate_rps=480.0 + i * 50.0,
            timestamp=ts_iso,
        )
        accumulator.record_traffic_assessment(ass, target_service="demo-api")

    captured_request = {}

    def mock_demand_handler(request: httpx.Request) -> httpx.Response:
        captured_request["url"] = str(request.url)
        captured_request["headers"] = dict(request.headers)
        captured_request["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=make_demand_forecast(predicted_rps=600.0).model_dump())

    def mock_traffic_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_traffic_assessment().model_dump())

    traffic_client = TrafficIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_traffic_handler))
    )
    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_demand_handler))
    )

    aggregator = ContextAggregatorService(
        traffic_client=traffic_client,
        demand_client=demand_client,
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
        demand_accumulator=accumulator,
    )

    context = await aggregator.aggregate_context(workload="demo-api", trace_id="trace-dispatch-01")

    assert context is not None
    assert "observations" in captured_request["body"]
    obs_payload = captured_request["body"]["observations"]
    assert len(obs_payload) == 3
    assert obs_payload[0]["rps"] == 480.0
    assert obs_payload[1]["rps"] == 530.0
    assert obs_payload[2]["rps"] == 580.0


# ==============================================================================
# 2. Outgoing Payload Provenance Check (No Fabrication)
# ==============================================================================

@pytest.mark.asyncio
async def test_outgoing_payload_matches_f2_accumulator_provenance(tmp_path):
    """Verify that observations in the outgoing JSON payload match exact F2 DB records."""
    db_path = str(tmp_path / "test_provenance.db")
    accumulator = DemandObservationAccumulator(db_path=db_path)

    now = time.time()
    ts1 = datetime.fromtimestamp(now - 180, tz=timezone.utc).isoformat()
    ts2 = datetime.fromtimestamp(now - 120, tz=timezone.utc).isoformat()
    ts3 = datetime.fromtimestamp(now - 60, tz=timezone.utc).isoformat()

    ass1 = make_traffic_assessment(total_rps=250.5, legitimate_rps=250.5, timestamp=ts1)
    ass2 = make_traffic_assessment(total_rps=310.2, legitimate_rps=310.2, timestamp=ts2)
    ass3 = make_traffic_assessment(total_rps=370.8, legitimate_rps=370.8, timestamp=ts3)

    accumulator.record_traffic_assessment(ass1, target_service="demo-api")
    accumulator.record_traffic_assessment(ass2, target_service="demo-api")
    accumulator.record_traffic_assessment(ass3, target_service="demo-api")

    expected_records = accumulator.get_historical_demand_observations(
        target_service="demo-api",
        historical_window_seconds=3600,
    )
    assert len(expected_records) == 3

    captured_observations = []

    def mock_demand_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode("utf-8"))
        captured_observations.extend(data.get("observations", []))
        return httpx.Response(200, json=make_demand_forecast().model_dump())

    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_demand_handler))
    )

    await demand_client.fetch_forecast(
        forecast_horizon_seconds=300,
        trace_id="trace-prov-check",
        target_service="demo-api",
        observations=expected_records,
    )

    assert len(captured_observations) == len(expected_records)
    for actual, expected in zip(captured_observations, expected_records):
        assert actual["timestamp"] == expected.timestamp
        assert actual["rps"] == expected.rps


# ==============================================================================
# 3. M2 HTTP Contract Conformance (POST /api/v1/demand/forecast)
# ==============================================================================

@pytest.mark.asyncio
async def test_m2_http_contract_conformance():
    """Verify outgoing request body against ForecastRequest schema structure."""
    captured_request = {}

    def mock_demand_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/demand/forecast"
        captured_request["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=make_demand_forecast().model_dump())

    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_demand_handler))
    )

    observations = [
        DemandObservation(timestamp=1725537600.0, rps=450.0),
        DemandObservation(timestamp=1725537660.0, rps=500.0),
    ]

    forecast = await demand_client.fetch_forecast(
        forecast_horizon_seconds=600,
        trace_id="trace-contract-test",
        target_service="demo-api",
        historical_window_seconds=1800,
        observations=observations,
    )

    body = captured_request["body"]
    assert body["forecast_horizon_seconds"] == 600
    assert body["target_service"] == "demo-api"
    assert body["trace_id"] == "trace-contract-test"
    assert body["historical_window_seconds"] == 1800
    assert len(body["observations"]) == 2
    assert body["observations"][0]["timestamp"] == 1725537600.0
    assert body["observations"][0]["rps"] == 450.0
    assert isinstance(forecast, DemandForecast)


# ==============================================================================
# 4. M2 DemandForecast Response Parsing and Validation
# ==============================================================================

@pytest.mark.asyncio
async def test_m2_demand_forecast_response_parsing_and_validation():
    """Verify DemandForecast response parsing and strict validation."""
    valid_payload = make_demand_forecast(predicted_rps=950.0, confidence=0.88).model_dump()

    def valid_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=valid_payload)

    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(valid_handler))
    )
    forecast = await demand_client.fetch_forecast()
    assert forecast.predicted_legitimate_rps == 950.0
    assert forecast.confidence == 0.88
    assert forecast.contract_version == "1.0.0"

    # Malformed response missing predicted_legitimate_rps
    def invalid_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"event_id": "evt-001", "trace_id": "t1"})

    invalid_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(invalid_handler))
    )
    with pytest.raises(UpstreamDemandIntelligenceError) as exc_info:
        await invalid_client.fetch_forecast()
    assert "validation failed" in exc_info.value.message.lower()


# ==============================================================================
# 5. Trace ID Propagation
# ==============================================================================

@pytest.mark.asyncio
async def test_trace_id_propagation_throughout_f3():
    """Verify trace_id header and payload propagation across the dispatch path."""
    expected_trace = "trace-f3-propagation-999"
    captured = {}

    def mock_demand_handler(request: httpx.Request) -> httpx.Response:
        captured["header_trace"] = request.headers.get("X-Trace-ID")
        data = json.loads(request.content.decode("utf-8"))
        captured["body_trace"] = data.get("trace_id")
        return httpx.Response(200, json=make_demand_forecast(trace_id=expected_trace).model_dump())

    def mock_traffic_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_traffic_assessment(trace_id=expected_trace).model_dump())

    traffic_client = TrafficIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_traffic_handler))
    )
    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_demand_handler))
    )

    aggregator = ContextAggregatorService(
        traffic_client=traffic_client,
        demand_client=demand_client,
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
        demand_accumulator=None,
    )

    ctx = await aggregator.aggregate_context(trace_id=expected_trace)
    assert ctx.trace_id == expected_trace
    assert captured["header_trace"] == expected_trace
    assert captured["body_trace"] == expected_trace
    assert ctx.demand_forecast.trace_id == expected_trace


# ==============================================================================
# 6. Empty Observation History Handling
# ==============================================================================

@pytest.mark.asyncio
async def test_empty_observation_history_handling(tmp_path):
    """Verify that when no observations exist in history, observations=None is sent to M2."""
    db_path = str(tmp_path / "empty_f3_history.db")
    accumulator = DemandObservationAccumulator(db_path=db_path)

    captured_body = {}

    def mock_demand_handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=make_demand_forecast().model_dump())

    def mock_traffic_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_traffic_assessment().model_dump())

    traffic_client = TrafficIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_traffic_handler))
    )
    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_demand_handler))
    )

    aggregator = ContextAggregatorService(
        traffic_client=traffic_client,
        demand_client=demand_client,
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
        demand_accumulator=accumulator,
    )

    context = await aggregator.aggregate_context()
    assert context is not None
    # When history is empty, observations key must NOT be present in payload
    assert "observations" not in captured_body


# ==============================================================================
# 7. M2 Error Handling (HTTP 500, Timeout, Malformed JSON)
# ==============================================================================

@pytest.mark.asyncio
async def test_m2_error_handling_mapped_to_aggregation_error():
    """Verify that upstream M2 errors cleanly map to AggregationError with source label."""
    # 1. HTTP 500
    def error_500_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal forecasting error")

    aggregator_500 = ContextAggregatorService(
        traffic_client=TrafficIntelligenceClient(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=make_traffic_assessment().model_dump())))
        ),
        demand_client=DemandIntelligenceClient(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(error_500_handler))
        ),
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
        demand_accumulator=None,
    )

    with pytest.raises(AggregationError) as exc_500:
        await aggregator_500.aggregate_context()
    assert exc_500.value.source == "Demand Intelligence"
    assert "HTTP 500" in exc_500.value.message

    # 2. Timeout
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Demand service timeout")

    aggregator_timeout = ContextAggregatorService(
        traffic_client=TrafficIntelligenceClient(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=make_traffic_assessment().model_dump())))
        ),
        demand_client=DemandIntelligenceClient(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
        ),
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
        demand_accumulator=None,
    )

    with pytest.raises(AggregationError) as exc_timeout:
        await aggregator_timeout.aggregate_context()
    assert exc_timeout.value.source == "Demand Intelligence"
    assert "timed out" in exc_timeout.value.message.lower()

    # 3. Malformed JSON
    def malformed_json_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="NOT_VALID_JSON{")

    aggregator_json = ContextAggregatorService(
        traffic_client=TrafficIntelligenceClient(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=make_traffic_assessment().model_dump())))
        ),
        demand_client=DemandIntelligenceClient(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(malformed_json_handler))
        ),
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
        demand_accumulator=None,
    )

    with pytest.raises(AggregationError) as exc_json:
        await aggregator_json.aggregate_context()
    assert exc_json.value.source == "Demand Intelligence"
    assert "malformed json" in exc_json.value.message.lower()


# ==============================================================================
# 8. Security Provenance: Suspicious Traffic Filtered Before M2
# ==============================================================================

@pytest.mark.asyncio
async def test_security_provenance_suspicious_traffic_filtered_before_m2(tmp_path):
    """Verify that suspicious DDoS traffic evaluated by M1 is filtered by F2 accumulator and never dispatched to M2."""
    db_path = str(tmp_path / "test_security_filter.db")
    accumulator = DemandObservationAccumulator(db_path=db_path)

    # Record 1 legitimate baseline observation relative to now
    now = time.time()
    legit_ts = datetime.fromtimestamp(now - 120, tz=timezone.utc).isoformat()
    legit_assessment = make_traffic_assessment(
        total_rps=400.0,
        legitimate_rps=400.0,
        risk_score=0.05,
        legitimacy_score=0.95,
        classification=TrafficClassification.LEGITIMATE,
        timestamp=legit_ts,
    )
    accumulator.record_traffic_assessment(legit_assessment, target_service="demo-api")

    # Now simulate an attack assessment from M1 (risk_score = 0.95, classification = MALICIOUS)
    hostile_ts = datetime.fromtimestamp(now - 60, tz=timezone.utc).isoformat()
    hostile_assessment = make_traffic_assessment(
        total_rps=5000.0,
        legitimate_rps=350.0,
        risk_score=0.95,
        legitimacy_score=0.05,
        classification=TrafficClassification.MALICIOUS,
        timestamp=hostile_ts,
    )
    # Attempt recording attack assessment
    record_res = accumulator.record_traffic_assessment(hostile_assessment, target_service="demo-api")
    assert record_res is None  # Filtered by F2 security policy!

    # Fetch observations from DB to dispatch to M2
    dispatched_obs = accumulator.get_historical_demand_observations(
        target_service="demo-api",
        historical_window_seconds=3600,
    )
    assert len(dispatched_obs) == 1
    assert dispatched_obs[0].rps == 400.0
    # Crucial security assertion: the 5000 total RPS attack flood is NEVER in the dispatch list!
    assert all(obs.rps < 1000.0 for obs in dispatched_obs)


# ==============================================================================
# 9. Full Aggregation into Decision Context & Decision Engine Semantics
# ==============================================================================

@pytest.mark.asyncio
async def test_full_aggregation_into_decision_context_preserves_decision_engine():
    """Verify end-to-end orchestration with dynamic DemandForecast produces deterministic ScalingDecision."""
    trace_id = "trace-e2e-decision-f3"

    def mock_traffic_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_traffic_assessment(trace_id=trace_id).model_dump())

    def mock_demand_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_demand_forecast(predicted_rps=850.0, trace_id=trace_id).model_dump())

    traffic_client = TrafficIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_traffic_handler))
    )
    demand_client = DemandIntelligenceClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_demand_handler))
    )

    aggregator = ContextAggregatorService(
        traffic_client=traffic_client,
        demand_client=demand_client,
        resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
        decision_engine=DecisionEngine(),
        demand_accumulator=None,
    )

    decision = await aggregator.orchestrate_decision(
        namespace="sentinelscale",
        workload="demo-api",
        trace_id=trace_id,
    )

    assert isinstance(decision, ScalingDecision)
    assert decision.trace_id == trace_id
    assert decision.action in (ScalingAction.HOLD, ScalingAction.SCALE, ScalingAction.RATE_LIMIT, ScalingAction.MITIGATE)
    assert decision.recommended_pods >= 2
    assert decision.dry_run is True
    assert decision.shadow_mode is True
    assert decision.predicted_legitimate_rps == 850.0

