import pytest
import uuid
from datetime import datetime, timezone
from app.models.context import DecisionContext, PolicyOverrides
from app.models.decision import ScalingAction
from app.models.resource import ResourceState
from app.models.traffic_contract import TrafficAssessment, TrafficClassification
from app.models.demand_contract import DemandForecast
from app.services.decision_engine import DecisionEngine


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
