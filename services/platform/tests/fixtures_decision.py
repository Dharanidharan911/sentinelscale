"""
Reusable contract-valid decision fixtures for Phase 3A tests.

These builders produce typed domain objects that conform to the frozen
JSON Schema contracts:
- TrafficAssessment  -> contracts/traffic/traffic_assessment.schema.json
- DemandForecast     -> contracts/demand/demand_forecast.schema.json
- ResourceState      -> contracts/resources/resource_state.schema.json
- DecisionContext    -> contracts/decisions/decision_context.schema.json

No HTTP, Kubernetes, Prometheus, or cross-service imports.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.models.context import DecisionContext, PolicyOverrides
from app.models.resource import ResourceState
from app.models.traffic_contract import TrafficAssessment, TrafficClassification
from app.models.demand_contract import DemandForecast


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_resource_state(
    running_pods: int = 4,
    cpu_utilization: float = 0.75,
    current_capacity_rps: float = 1400.0,
    trace_id: str = "test-trace",
) -> ResourceState:
    return ResourceState(
        event_id=str(uuid.uuid4()),
        trace_id=trace_id,
        timestamp=now_iso(),
        contract_version="1.0.0",
        service_version="0.1.0",
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=cpu_utilization,
        memory_utilization=0.50,
        cpu_requested_cores=4.0,
        cpu_limit_cores=8.0,
        memory_requested_bytes=4294967296,
        memory_limit_bytes=8589934592,
        running_pods=running_pods,
        desired_pods=running_pods,
        pending_pods=0,
        request_rate=current_capacity_rps,
        p95_latency_ms=45.0,
        error_rate=0.001,
        current_capacity_rps=current_capacity_rps,
        estimated_required_capacity_rps=current_capacity_rps,
        estimated_resource_waste=0.0,
    )


def make_traffic_assessment(
    classification: TrafficClassification = TrafficClassification.SUSPICIOUS,
    risk_score: float = 0.84,
    total_rps: float = 2500.0,
    legitimate_rps: float = 850.0,
    suspicious_rps: float = 1650.0,
    confidence: float = 0.91,
    trace_id: str = "test-trace",
) -> TrafficAssessment:
    return TrafficAssessment(
        event_id=str(uuid.uuid4()),
        trace_id=trace_id,
        timestamp=now_iso(),
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="traffic-v0 (mock)",
        window_seconds=60,
        total_rps=total_rps,
        legitimate_rps_estimate=legitimate_rps,
        suspicious_rps_estimate=suspicious_rps,
        risk_score=risk_score,
        legitimacy_score=round(1.0 - risk_score, 2),
        confidence=confidence,
        classification=classification,
        top_signals=["high_burst_rate"] if risk_score >= 0.5 else [],
    )


def make_demand_forecast(
    predicted_legitimate_rps: float = 1100.0,
    lower_bound_rps: Optional[float] = None,
    upper_bound_rps: Optional[float] = None,
    confidence: float = 0.91,
    trace_id: str = "test-trace",
) -> DemandForecast:
    return DemandForecast(
        event_id=str(uuid.uuid4()),
        trace_id=trace_id,
        generated_at=now_iso(),
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="demand-v0 (mock)",
        forecast_horizon_seconds=300,
        predicted_legitimate_rps=predicted_legitimate_rps,
        lower_bound_rps=lower_bound_rps if lower_bound_rps is not None else predicted_legitimate_rps * 0.9,
        upper_bound_rps=upper_bound_rps if upper_bound_rps is not None else predicted_legitimate_rps * 1.1,
        confidence=confidence,
    )


def make_decision_context(
    trace_id: str = "test-trace",
    traffic_assessment: Optional[TrafficAssessment] = None,
    demand_forecast: Optional[DemandForecast] = None,
    resource_state: Optional[ResourceState] = None,
    policy_overrides: Optional[PolicyOverrides] = None,
    dry_run: bool = True,
    shadow_mode: bool = True,
) -> DecisionContext:
    return DecisionContext(
        context_id=str(uuid.uuid4()),
        trace_id=trace_id,
        timestamp=now_iso(),
        contract_version="1.0.0",
        target_workload="demo-api",
        traffic_assessment=traffic_assessment or make_traffic_assessment(trace_id=trace_id),
        demand_forecast=demand_forecast or make_demand_forecast(trace_id=trace_id),
        resource_state=resource_state or make_resource_state(trace_id=trace_id),
        policy_overrides=policy_overrides,
        dry_run=dry_run,
        shadow_mode=shadow_mode,
    )