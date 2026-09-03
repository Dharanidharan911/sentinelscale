import pytest
from app.models.context import DecisionContext
from app.models.decision import ScalingAction
from app.models.demand_contract import DemandForecast
from app.models.resource import ResourceState
from app.models.traffic_contract import TrafficAssessment, TrafficClassification
from app.services.decision_engine import DecisionEngine


@pytest.mark.asyncio
async def test_integration_scenario_a_attack_heavy_traffic():
    """
    Scenario A: Volumetric attack traffic with moderate legitimate demand.
    Total: 6000 RPS, Legitimate estimate: 780 RPS, Predicted legitimate: 1200 RPS.
    Current capacity: 1400 RPS (4 pods @ 350 RPS).
    DecisionEngine must HOLD and prevent HPA reactive overprovisioning.
    """
    engine = DecisionEngine()

    traffic = TrafficAssessment(
        event_id="int-m1-a",
        trace_id="trace-int-a",
        timestamp="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="traffic-rules-v1",
        window_seconds=60,
        total_rps=6000.0,
        legitimate_rps_estimate=780.0,
        suspicious_rps_estimate=5220.0,
        risk_score=0.85,
        legitimacy_score=0.13,
        confidence=0.90,
        classification=TrafficClassification.MALICIOUS,
        top_signals=["critical_burst_rate", "critical_ip_concentration"],
    )

    demand = DemandForecast(
        event_id="int-m2-a",
        trace_id="trace-int-a",
        generated_at="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="demand-v0",
        forecast_horizon_seconds=300,
        predicted_legitimate_rps=1200.0,
        lower_bound_rps=1050.0,
        upper_bound_rps=1350.0,
        confidence=0.92,
    )

    resource = ResourceState(
        event_id="int-res-a",
        trace_id="trace-int-a",
        timestamp="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=0.95,
        memory_utilization=0.70,
        cpu_requested_cores=4.0,
        cpu_limit_cores=8.0,
        memory_requested_bytes=4294967296,
        memory_limit_bytes=8589934592,
        running_pods=4,
        desired_pods=4,
        pending_pods=0,
        request_rate=6000.0,
        p95_latency_ms=120.0,
        error_rate=0.08,
        current_capacity_rps=1400.0,
        estimated_required_capacity_rps=1200.0,
        estimated_resource_waste=0.0,
    )

    context = DecisionContext(
        context_id="ctx-int-a",
        trace_id="trace-int-a",
        timestamp="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        target_workload="demo-api",
        traffic_assessment=traffic,
        demand_forecast=demand,
        resource_state=resource,
        dry_run=True,
        shadow_mode=True,
    )

    decision = await engine.evaluate_decision(context)

    assert decision.action == ScalingAction.HOLD
    assert decision.recommended_pods == 4
    assert decision.baseline_hpa_recommended_pods == 6
    assert decision.pod_delta_vs_baseline == -2
    assert decision.dry_run is True
    assert decision.shadow_mode is True
    assert "Prevented reactive overprovisioning of 2 pods" in decision.reason


@pytest.mark.asyncio
async def test_integration_scenario_b_legitimate_demand_surge():
    """
    Scenario B: Genuine business demand surge.
    Total: 5600 RPS, Legitimate estimate: 5600 RPS, Predicted legitimate: 5600 RPS.
    Current capacity: 1400 RPS (4 pods).
    DecisionEngine must SCALE based on legitimate demand within surge protection bounds.
    """
    engine = DecisionEngine()

    traffic = TrafficAssessment(
        event_id="int-m1-b",
        trace_id="trace-int-b",
        timestamp="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="traffic-rules-v1",
        window_seconds=60,
        total_rps=5600.0,
        legitimate_rps_estimate=5600.0,
        suspicious_rps_estimate=0.0,
        risk_score=0.17,
        legitimacy_score=0.83,
        confidence=0.88,
        classification=TrafficClassification.LEGITIMATE,
        top_signals=["critical_burst_rate", "distributed_client_pool"],
    )

    demand = DemandForecast(
        event_id="int-m2-b",
        trace_id="trace-int-b",
        generated_at="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="demand-v0",
        forecast_horizon_seconds=300,
        predicted_legitimate_rps=5600.0,
        lower_bound_rps=5200.0,
        upper_bound_rps=6000.0,
        confidence=0.95,
    )

    resource = ResourceState(
        event_id="int-res-b",
        trace_id="trace-int-b",
        timestamp="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=0.92,
        memory_utilization=0.75,
        cpu_requested_cores=4.0,
        cpu_limit_cores=8.0,
        memory_requested_bytes=4294967296,
        memory_limit_bytes=8589934592,
        running_pods=4,
        desired_pods=4,
        pending_pods=0,
        request_rate=5600.0,
        p95_latency_ms=85.0,
        error_rate=0.001,
        current_capacity_rps=1400.0,
        estimated_required_capacity_rps=5600.0,
        estimated_resource_waste=0.0,
    )

    context = DecisionContext(
        context_id="ctx-int-b",
        trace_id="trace-int-b",
        timestamp="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        target_workload="demo-api",
        traffic_assessment=traffic,
        demand_forecast=demand,
        resource_state=resource,
        dry_run=True,
        shadow_mode=True,
    )

    decision = await engine.evaluate_decision(context)

    assert decision.action == ScalingAction.SCALE
    assert decision.recommended_pods == 8  # Capped at max 2x step surge (4 * 2 = 8)
    assert decision.dry_run is True


@pytest.mark.asyncio
async def test_integration_scenario_c_low_demand_scale_down():
    """
    Scenario C: Workload demand drops significantly below current capacity.
    Predicted demand: 350 RPS, Current capacity: 1400 RPS (4 pods).
    DecisionEngine recommends scale-down to min_pods.
    """
    engine = DecisionEngine()

    traffic = TrafficAssessment(
        event_id="int-m1-c",
        trace_id="trace-int-c",
        timestamp="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="traffic-rules-v1",
        window_seconds=60,
        total_rps=350.0,
        legitimate_rps_estimate=350.0,
        suspicious_rps_estimate=0.0,
        risk_score=0.05,
        legitimacy_score=0.95,
        confidence=0.90,
        classification=TrafficClassification.LEGITIMATE,
        top_signals=[],
    )

    demand = DemandForecast(
        event_id="int-m2-c",
        trace_id="trace-int-c",
        generated_at="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="demand-v0",
        forecast_horizon_seconds=300,
        predicted_legitimate_rps=350.0,
        lower_bound_rps=300.0,
        upper_bound_rps=400.0,
        confidence=0.90,
    )

    resource = ResourceState(
        event_id="int-res-c",
        trace_id="trace-int-c",
        timestamp="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=0.20,
        memory_utilization=0.30,
        cpu_requested_cores=4.0,
        cpu_limit_cores=8.0,
        memory_requested_bytes=4294967296,
        memory_limit_bytes=8589934592,
        running_pods=4,
        desired_pods=4,
        pending_pods=0,
        request_rate=350.0,
        p95_latency_ms=15.0,
        error_rate=0.0,
        current_capacity_rps=1400.0,
        estimated_required_capacity_rps=350.0,
        estimated_resource_waste=0.75,
    )

    context = DecisionContext(
        context_id="ctx-int-c",
        trace_id="trace-int-c",
        timestamp="2026-09-03T17:00:00Z",
        contract_version="1.0.0",
        target_workload="demo-api",
        traffic_assessment=traffic,
        demand_forecast=demand,
        resource_state=resource,
        dry_run=True,
        shadow_mode=True,
    )

    decision = await engine.evaluate_decision(context)

    assert decision.action == ScalingAction.SCALE
    assert decision.recommended_pods == 2  # Clamped to min_pods=2
    assert decision.dry_run is True

