import pytest
import uuid
from datetime import datetime, timezone
from app.config.settings import settings
from app.models.context import DecisionContext, PolicyOverrides
from app.models.decision import ScalingAction
from app.models.resource import ResourceState
from app.models.traffic_contract import TrafficAssessment, TrafficClassification
from app.models.demand_contract import DemandForecast
from app.services.decision_engine import DecisionEngine
from tests.fixtures_decision import (
    make_decision_context,
    make_demand_forecast,
    make_resource_state,
    make_traffic_assessment,
)


@pytest.fixture
def sample_resource_state():
    return ResourceState(
        event_id=str(uuid.uuid4()),
        trace_id="test-trace",
        timestamp=datetime.now(timezone.utc).isoformat(),
        contract_version="1.0.0",
        service_version="0.1.0",
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=0.85,
        memory_utilization=0.60,
        cpu_requested_cores=4.0,
        cpu_limit_cores=8.0,
        memory_requested_bytes=4294967296,
        memory_limit_bytes=8589934592,
        running_pods=4,
        desired_pods=4,
        pending_pods=0,
        request_rate=2800.0,
        p95_latency_ms=65.0,
        error_rate=0.01,
        current_capacity_rps=1400.0,
        estimated_required_capacity_rps=1400.0,
        estimated_resource_waste=0.0
    )


@pytest.mark.asyncio
async def test_decision_engine_holds_under_attack_when_legitimate_demand_is_within_capacity(sample_resource_state):
    engine = DecisionEngine()
    context = DecisionContext(
        context_id=str(uuid.uuid4()),
        trace_id="trace-test",
        timestamp=datetime.now(timezone.utc).isoformat(),
        contract_version="1.0.0",
        target_workload="demo-api",
        traffic_assessment=TrafficAssessment(
            event_id=str(uuid.uuid4()),
            trace_id="trace-test",
            timestamp=datetime.now(timezone.utc).isoformat(),
            contract_version="1.0.0",
            service_version="0.1.0",
            model_version="traffic-v0 (mock)",
            window_seconds=60,
            total_rps=2800.0,
            legitimate_rps_estimate=900.0,
            suspicious_rps_estimate=1900.0,
            risk_score=0.89,
            legitimacy_score=0.32,
            confidence=0.95,
            classification=TrafficClassification.SUSPICIOUS,
            top_signals=["ip_burst", "anomalous_user_agent"]
        ),
        demand_forecast=DemandForecast(
            event_id=str(uuid.uuid4()),
            trace_id="trace-test",
            generated_at=datetime.now(timezone.utc).isoformat(),
            contract_version="1.0.0",
            service_version="0.1.0",
            model_version="demand-v0 (mock)",
            forecast_horizon_seconds=300,
            predicted_legitimate_rps=1000.0,
            lower_bound_rps=900.0,
            upper_bound_rps=1100.0,
            confidence=0.92
        ),
        resource_state=sample_resource_state,
        dry_run=True,
        shadow_mode=True
    )

    decision = await engine.evaluate_decision(context)

    # In this scenario:
    # - Raw CPU is 85%, total traffic is 2800 RPS (Baseline HPA wants to scale up)
    # - Legitimate demand is 1000 RPS, which fits in current capacity (1400 RPS)
    # - SentinelScale holds capacity, avoiding expensive reactive overprovisioning for malicious traffic
    assert decision.action == ScalingAction.HOLD
    assert decision.dry_run is True
    assert decision.shadow_mode is True
    assert decision.baseline_hpa_recommended_pods > decision.recommended_pods
    assert decision.pod_delta_vs_baseline < 0


@pytest.mark.asyncio
async def test_decision_engine_scales_when_legitimate_demand_exceeds_capacity(sample_resource_state):
    engine = DecisionEngine()
    context = DecisionContext(
        context_id=str(uuid.uuid4()),
        trace_id="trace-test-scale",
        timestamp=datetime.now(timezone.utc).isoformat(),
        contract_version="1.0.0",
        target_workload="demo-api",
        traffic_assessment=TrafficAssessment(
            event_id=str(uuid.uuid4()),
            trace_id="trace-test-scale",
            timestamp=datetime.now(timezone.utc).isoformat(),
            contract_version="1.0.0",
            service_version="0.1.0",
            model_version="traffic-v0 (mock)",
            window_seconds=60,
            total_rps=2200.0,
            legitimate_rps_estimate=2100.0,
            suspicious_rps_estimate=100.0,
            risk_score=0.10,
            legitimacy_score=0.95,
            confidence=0.95,
            classification=TrafficClassification.LEGITIMATE,
            top_signals=[]
        ),
        demand_forecast=DemandForecast(
            event_id=str(uuid.uuid4()),
            trace_id="trace-test-scale",
            generated_at=datetime.now(timezone.utc).isoformat(),
            contract_version="1.0.0",
            service_version="0.1.0",
            model_version="demand-v0 (mock)",
            forecast_horizon_seconds=300,
            predicted_legitimate_rps=2400.0,
            lower_bound_rps=2200.0,
            upper_bound_rps=2600.0,
            confidence=0.94
        ),
        resource_state=sample_resource_state,
        dry_run=True,
        shadow_mode=True
    )

    decision = await engine.evaluate_decision(context)

    # Legitimate demand (2400 RPS) exceeds capacity (1400 RPS), action must be SCALE
    assert decision.action == ScalingAction.SCALE
    assert decision.recommended_pods > sample_resource_state.running_pods
    assert decision.dry_run is True


# =========================================================================
# Phase 3A — Decision Foundation tests (typed pipeline, guardrails, shadow)
# =========================================================================


@pytest.mark.asyncio
async def test_hold_when_legitimate_demand_fits_current_capacity():
    """Low-risk workload whose legitimate forecast fits capacity must HOLD."""
    engine = DecisionEngine()
    context = make_decision_context(
        trace_id="phase3a-hold",
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.LEGITIMATE,
            risk_score=0.10,
            total_rps=1000.0,
            legitimate_rps=950.0,
            suspicious_rps=50.0,
            trace_id="phase3a-hold",
        ),
        demand_forecast=make_demand_forecast(predicted_legitimate_rps=1000.0, trace_id="phase3a-hold"),
        resource_state=make_resource_state(running_pods=4, current_capacity_rps=1400.0, trace_id="phase3a-hold"),
    )

    decision = await engine.evaluate_decision(context)

    assert decision.action == ScalingAction.HOLD
    assert decision.recommended_pods <= decision.current_pods


@pytest.mark.asyncio
async def test_scale_when_legitimate_demand_exceeds_capacity_with_low_risk():
    """The 6000 total / 5600 legitimate / 1400 capacity example: must SCALE."""
    engine = DecisionEngine()
    context = make_decision_context(
        trace_id="phase3a-scale-legit",
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.LEGITIMATE,
            risk_score=0.20,
            total_rps=6000.0,
            legitimate_rps=5600.0,
            suspicious_rps=400.0,
            trace_id="phase3a-scale-legit",
        ),
        demand_forecast=make_demand_forecast(predicted_legitimate_rps=5600.0, trace_id="phase3a-scale-legit"),
        resource_state=make_resource_state(running_pods=4, current_capacity_rps=1400.0, trace_id="phase3a-scale-legit"),
    )

    decision = await engine.evaluate_decision(context)

    assert decision.action == ScalingAction.SCALE
    # ceil(5600 / 350) = 16 -> clamped to max_pods=20 stays, but step-up limits to 8
    assert decision.recommended_pods > decision.current_pods
    assert decision.recommended_pods == 8  # 2x step-up surge protection from 4 pods


@pytest.mark.asyncio
async def test_suspicious_traffic_does_not_trigger_scaling_when_demand_within_capacity():
    """The 6000 total / 1200 legitimate / 1400 capacity example: must NOT scale for total traffic."""
    engine = DecisionEngine()
    context = make_decision_context(
        trace_id="phase3a-attack-hold",
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.MALICIOUS,
            risk_score=0.90,
            total_rps=6000.0,
            legitimate_rps=1200.0,
            suspicious_rps=4800.0,
            trace_id="phase3a-attack-hold",
        ),
        demand_forecast=make_demand_forecast(predicted_legitimate_rps=1200.0, trace_id="phase3a-attack-hold"),
        resource_state=make_resource_state(running_pods=4, current_capacity_rps=1400.0, trace_id="phase3a-attack-hold"),
    )

    decision = await engine.evaluate_decision(context)

    assert decision.action == ScalingAction.HOLD
    # SentinelScale must not provision for total (6000 RPS -> 18 pods); only legitimate demand
    assert decision.recommended_pods <= decision.current_pods
    # A blind reactive HPA driven by total load would recommend far more pods
    assert decision.baseline_hpa_recommended_pods > decision.recommended_pods
    assert decision.pod_delta_vs_baseline < 0


@pytest.mark.asyncio
async def test_forecast_demand_drives_recommendation():
    """Higher forecast demand must yield a higher recommended pod count than lower demand."""
    engine = DecisionEngine()

    low_demand_context = make_decision_context(
        trace_id="phase3a-forecast-low",
        demand_forecast=make_demand_forecast(predicted_legitimate_rps=700.0, trace_id="phase3a-forecast-low"),
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.LEGITIMATE,
            risk_score=0.10,
            total_rps=700.0,
            legitimate_rps=700.0,
            suspicious_rps=0.0,
            trace_id="phase3a-forecast-low",
        ),
        resource_state=make_resource_state(running_pods=4, current_capacity_rps=1400.0, trace_id="phase3a-forecast-low"),
    )
    high_demand_context = make_decision_context(
        trace_id="phase3a-forecast-high",
        demand_forecast=make_demand_forecast(predicted_legitimate_rps=2800.0, trace_id="phase3a-forecast-high"),
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.LEGITIMATE,
            risk_score=0.10,
            total_rps=2800.0,
            legitimate_rps=2800.0,
            suspicious_rps=0.0,
            trace_id="phase3a-forecast-high",
        ),
        resource_state=make_resource_state(running_pods=4, current_capacity_rps=1400.0, trace_id="phase3a-forecast-high"),
    )

    low_decision = await engine.evaluate_decision(low_demand_context)
    high_decision = await engine.evaluate_decision(high_demand_context)

    assert high_decision.recommended_pods > low_decision.recommended_pods
    assert high_decision.predicted_legitimate_rps == 2800.0
    assert low_decision.predicted_legitimate_rps == 700.0


def test_baseline_hpa_recommendation_is_deterministic():
    """Identical resource state must always yield an identical baseline recommendation."""
    calc_state = make_resource_state(running_pods=4, cpu_utilization=0.90, current_capacity_rps=1400.0)

    from app.services.baseline_hpa import BaselineHPACalculator
    calculator = BaselineHPACalculator()

    results = {calculator.calculate_baseline_replicas(calc_state) for _ in range(10)}

    assert len(results) == 1
    baseline_pods = results.pop()
    assert baseline_pods >= settings.DEFAULT_MIN_PODS
    assert baseline_pods <= settings.DEFAULT_MAX_PODS


@pytest.mark.asyncio
async def test_sentinelscale_recommendation_is_separate_from_baseline():
    """SentinelScale and baseline HPA recommendations are computed and reported independently."""
    engine = DecisionEngine()
    context = make_decision_context(
        trace_id="phase3a-separation",
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.SUSPICIOUS,
            risk_score=0.89,
            total_rps=2800.0,
            legitimate_rps=900.0,
            suspicious_rps=1900.0,
            trace_id="phase3a-separation",
        ),
        demand_forecast=make_demand_forecast(predicted_legitimate_rps=1000.0, trace_id="phase3a-separation"),
        # High CPU would make a reactive HPA scale out; legitimate demand does not require it
        resource_state=make_resource_state(
            running_pods=4,
            cpu_utilization=0.85,
            current_capacity_rps=1400.0,
            trace_id="phase3a-separation",
        ),
    )

    decision = await engine.evaluate_decision(context)

    # Both recommendations present, independently observable
    assert isinstance(decision.baseline_hpa_recommended_pods, int)
    assert isinstance(decision.recommended_pods, int)
    assert decision.baseline_hpa_recommended_pods >= settings.DEFAULT_MIN_PODS
    assert decision.baseline_hpa_recommended_pods <= settings.DEFAULT_MAX_PODS
    # Reactive HPA sees 85% CPU vs 70% target -> wants 5+ pods; SentinelScale holds for 1000 RPS
    assert decision.baseline_hpa_recommended_pods > decision.recommended_pods
    assert decision.pod_delta_vs_baseline == decision.recommended_pods - decision.baseline_hpa_recommended_pods


@pytest.mark.asyncio
async def test_guardrail_constrains_unsafe_recommendation():
    """An unsafe engine recommendation (breaching max/step-up) is constrained by policy."""
    engine = DecisionEngine()
    context = make_decision_context(
        trace_id="phase3a-constrain",
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.LEGITIMATE,
            risk_score=0.05,
            total_rps=9000.0,
            legitimate_rps=9000.0,
            suspicious_rps=0.0,
            trace_id="phase3a-constrain",
        ),
        demand_forecast=make_demand_forecast(predicted_legitimate_rps=9000.0, trace_id="phase3a-constrain"),
        resource_state=make_resource_state(running_pods=4, current_capacity_rps=1400.0, trace_id="phase3a-constrain"),
    )

    decision = await engine.evaluate_decision(context)

    # Raw recommendation would be ceil(9000/350)=26 pods; policy must constrain it.
    # Guardrail order: max ceiling (20) fires before the step-up rule (documented behavior).
    assert decision.recommended_pods <= settings.DEFAULT_MAX_PODS
    assert decision.recommended_pods < 26  # unconstrained recommendation was 26
    assert "maximum policy safety ceiling" in decision.reason


@pytest.mark.asyncio
async def test_dry_run_always_produces_recommendation_only():
    """Even with dry_run=False in the context, output remains recommendation-only (hardcoded safety)."""
    engine = DecisionEngine()
    context = make_decision_context(
        trace_id="phase3a-dry-run",
        dry_run=False,  # Attempt to disable dry-run must NOT propagate
        shadow_mode=False,
    )

    decision = await engine.evaluate_decision(context)

    assert decision.dry_run is True  # Code-level safety guarantee (ADR-002)
    assert isinstance(decision.action, ScalingAction)
    assert decision.recommended_pods >= settings.DEFAULT_MIN_PODS


@pytest.mark.asyncio
async def test_shadow_mode_is_recommendation_only_and_mirrored():
    """shadow_mode produces recommendations and is mirrored into the decision output."""
    engine = DecisionEngine()
    context = make_decision_context(trace_id="phase3a-shadow", shadow_mode=True, dry_run=True)

    decision = await engine.evaluate_decision(context)

    assert decision.shadow_mode is True
    assert decision.dry_run is True


@pytest.mark.asyncio
async def test_no_actuation_engine_is_pure_computation():
    """The engine computes a typed decision object without any external actuation calls."""
    import inspect
    from app.services import decision_engine as engine_module

    engine = DecisionEngine()
    context = make_decision_context(trace_id="phase3a-pure")

    decision = await engine.evaluate_decision(context)

    # Output is a pure typed model, not a side effect
    from app.models.decision import ScalingDecision
    assert isinstance(decision, ScalingDecision)
    # Engine module must not reference actuation mechanisms
    source = inspect.getsource(engine_module)
    for forbidden in ["kubectl", "httpx", "requests.", "subprocess", "patch(", "scale(", "AioClient"]:
        assert forbidden not in source, f"Forbidden actuation/network primitive in engine: {forbidden}"


@pytest.mark.asyncio
async def test_decision_output_metadata_is_valid():
    """Decision metadata: valid UUIDs, ISO-8601 timestamp, versions from settings."""
    engine = DecisionEngine()
    context = make_decision_context(trace_id="phase3a-metadata")

    decision = await engine.evaluate_decision(context)

    parsed_decision_id = uuid.UUID(decision.decision_id)
    parsed_event_id = uuid.UUID(decision.event_id)
    assert parsed_decision_id.version == 4
    assert parsed_event_id.version == 4
    datetime.fromisoformat(decision.timestamp)  # raises if not ISO-8601
    assert decision.contract_version == settings.CONTRACT_VERSION
    assert decision.service_version == settings.SERVICE_VERSION
    assert decision.model_version == settings.MODEL_VERSION
    assert decision.policy == "default-safe-guardrail-v1"
    assert 0.0 <= decision.confidence <= 1.0
    assert 0.0 <= decision.traffic_risk <= 1.0


@pytest.mark.asyncio
async def test_trace_id_propagates_to_decision():
    """Context trace_id must propagate to the ScalingDecision; event_id from traffic assessment."""
    engine = DecisionEngine()
    context = make_decision_context(trace_id="phase3a-trace-prop")

    decision = await engine.evaluate_decision(context)

    assert decision.trace_id == "phase3a-trace-prop"
    assert decision.event_id == context.traffic_assessment.event_id
