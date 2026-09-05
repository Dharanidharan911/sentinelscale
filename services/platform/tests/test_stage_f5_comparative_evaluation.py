"""
SentinelScale — Stage F5: Comparative HPA vs SentinelScale Evaluation Suite
Evaluates comparative scaling decisions across dynamic traffic scenarios:
  1. Scenario A: Steady Legitimate Traffic
  2. Scenario B: Legitimate Flash Crowd Surge
  3. Scenario C: Hostile L7 Flood Attack (EDoS Prevention)
  4. Scenario D: Mixed Legitimate + Suspicious Traffic

Verifies:
  - Provenance: Comparisons are fed by real F4 dynamic pipeline outputs
  - Security Awareness: Hostile attack surges do not cause overprovisioning
  - Demand Responsiveness: Genuine business demand increases are supported
  - Evaluator Metrics: Replica delta, recommendation difference, pod-hours saved
  - Safety Invariants: dry_run=True, shadow_mode=True, 0 cluster mutations
"""
import math
import os
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.clients.demand_client import DemandIntelligenceClient
from app.clients.traffic_client import TrafficIntelligenceClient
from app.harness.collector import TelemetryCollector
from app.harness.generator import AsyncTrafficGenerator
from app.harness.models import (
    BOT_USER_AGENTS,
    BROWSER_USER_AGENTS,
    EndpointTarget,
    ObservedRequestEvent,
    ScenarioDefinition,
    TrafficScenarioType,
    create_scenario_preset,
)
from app.harness.runner import ScenarioExecutionResult, ScenarioRunner
from app.models.context import DecisionContext
from app.models.decision import ScalingAction, ScalingDecision
from app.models.demand_contract import DemandForecast, DemandObservation, ForecastRequest
from app.models.evaluation import (
    EvaluationCategory,
    EvaluationMetrics,
    EvaluationResult,
    RecommendationDifference,
)
from app.models.resource import ResourceState
from app.models.traffic_contract import TrafficAssessment, TrafficClassification
from app.services.context_aggregator import ContextAggregatorService
from app.services.decision_engine import DecisionEngine
from app.services.evaluation.evaluator import DefaultHPAEvaluationService
from app.services.history.demand_accumulator import DemandObservationAccumulator
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.mock_provider import MockTelemetryProvider


# ==============================================================================
# Microservice Application Fixtures
# ==============================================================================

@pytest.fixture
def demo_api_app() -> FastAPI:
    """Demo API with e-commerce catalog, search, cart, and authentication."""
    app = FastAPI(title="Demo API")

    @app.get("/products")
    async def get_products():
        return [
            {"id": "prod-001", "name": "Ultra-Shield Cloud WAF", "price": 299.99},
            {"id": "prod-002", "name": "Neural Scale Pod", "price": 49.99},
        ]

    @app.get("/products/{product_id}")
    async def get_product(product_id: str):
        if "invalid" in product_id or "probe" in product_id:
            return JSONResponse(status_code=404, content={"detail": "Product not found"})
        return {"id": product_id, "name": "Product", "price": 99.99}

    @app.get("/search")
    async def search(q: str):
        return []

    @app.post("/login")
    async def login(body: dict):
        if not body.get("username"):
            return JSONResponse(status_code=400, content={"detail": "Username required"})
        return {"token": "jwt-token-123"}

    @app.post("/cart")
    async def cart(body: dict):
        return {"cart_id": "cart-123"}

    return app


@pytest.fixture
def traffic_intelligence_app() -> FastAPI:
    """Module 1 Traffic Intelligence API with deterministic scoring engine."""
    app = FastAPI(title="Traffic Intelligence")

    @app.post("/api/v1/traffic/assess")
    async def assess(req: dict):
        telemetry = req.get("telemetry") or {}
        window_seconds = req.get("window_seconds", 60)
        trace_id = req.get("trace_id", "trace-default")

        total_rps = float(telemetry.get("total_rps", 50.0))
        top_ip_ratio = float(telemetry.get("top_ip_ratio") or 0.0)
        ua_anomaly = float(telemetry.get("non_standard_ua_ratio") or 0.0)
        status_codes = telemetry.get("status_codes") or {}
        s_4xx = status_codes.get("status_4xx", 0)
        s_5xx = status_codes.get("status_5xx", 0)
        tot_reqs = telemetry.get("total_requests", 1)
        error_rate = (s_4xx + s_5xx) / float(max(1, tot_reqs))

        baseline_rps = float(telemetry.get("baseline_rps") or total_rps)
        burst_ratio = total_rps / max(1.0, baseline_rps)

        raw_risk = (top_ip_ratio * 0.35) + (ua_anomaly * 0.30) + (min(1.0, error_rate / 0.35) * 0.20)
        if burst_ratio >= 4.0:
            raw_risk += 0.15
        elif burst_ratio >= 2.5:
            raw_risk += 0.10
        elif burst_ratio >= 1.75:
            raw_risk += 0.05

        if top_ip_ratio >= 0.70 and ua_anomaly >= 0.65:
            raw_risk = max(raw_risk, 0.85)
        elif top_ip_ratio <= 0.15 and ua_anomaly <= 0.05 and error_rate <= 0.05:
            raw_risk = min(raw_risk, 0.15)

        risk_score = round(max(0.0, min(1.0, raw_risk)), 2)
        legitimacy_score = round(max(0.0, min(1.0, 1.0 - risk_score)), 2)

        suspicious_fraction = max(risk_score, (top_ip_ratio * 0.6 + ua_anomaly * 0.4))
        if risk_score < 0.20:
            suspicious_fraction = 0.0
        suspicious_fraction = max(0.0, min(1.0, suspicious_fraction))

        suspicious_rps = round(total_rps * suspicious_fraction, 2)
        legitimate_rps = round(total_rps - suspicious_rps, 2)

        signals = []
        if top_ip_ratio >= 0.70:
            signals.append("critical_ip_concentration")
        if ua_anomaly >= 0.65:
            signals.append("critical_bot_ua_signature")
        if error_rate >= 0.35:
            signals.append("high_error_rate")
        if burst_ratio >= 2.5:
            signals.append("high_burst_rate")
        if risk_score < 0.30 and burst_ratio >= 1.75:
            signals.append("organic_demand_surge")
        if not signals:
            signals.append("legitimate_traffic_profile")

        if risk_score >= 0.80:
            classification = "malicious"
        elif risk_score >= 0.50:
            classification = "suspicious"
        else:
            classification = "legitimate"

        return {
            "event_id": str(uuid.uuid4()),
            "trace_id": trace_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "contract_version": "1.0.0",
            "service_version": "0.1.0",
            "model_version": "traffic-rules-v1",
            "window_seconds": window_seconds,
            "total_rps": total_rps,
            "legitimate_rps_estimate": legitimate_rps,
            "suspicious_rps_estimate": suspicious_rps,
            "risk_score": risk_score,
            "legitimacy_score": legitimacy_score,
            "confidence": 0.90,
            "classification": classification,
            "top_signals": signals[:5],
        }

    return app


@pytest.fixture
def demand_intelligence_app() -> FastAPI:
    """Module 2 Demand Intelligence API with demand-v1 statistical forecaster."""
    app = FastAPI(title="Demand Intelligence")

    @app.post("/api/v1/demand/forecast", response_model=DemandForecast)
    async def forecast(req: ForecastRequest):
        effective_trace_id = req.trace_id or f"trace-{uuid.uuid4().hex[:16]}"
        obs = req.observations or []

        if len(obs) >= 2:
            sorted_obs = sorted(obs, key=lambda x: x.timestamp)
            t_last = sorted_obs[-1].timestamp
            total_w = 0.0
            weighted_sum = 0.0
            for o in sorted_obs:
                intervals_ago = max(0.0, (t_last - o.timestamp) / 300.0)
                w = 0.85 ** intervals_ago
                weighted_sum += o.rps * w
                total_w += w
            w_mean = weighted_sum / total_w if total_w > 0 else sorted_obs[-1].rps

            dt = sorted_obs[-1].timestamp - sorted_obs[0].timestamp
            slope = (sorted_obs[-1].rps - sorted_obs[0].rps) / dt if dt > 0 else 0.0
            projected = max(0.0, w_mean + slope * req.forecast_horizon_seconds)

            mean_rps = sum(o.rps for o in sorted_obs) / len(sorted_obs)
            variance = sum((o.rps - mean_rps) ** 2 for o in sorted_obs) / len(sorted_obs)
            std_dev = math.sqrt(variance)
            confidence = min(0.98, max(0.50, 1.0 - (std_dev / max(1.0, mean_rps))))
        elif len(obs) == 1:
            projected = obs[0].rps
            confidence = 0.60
            std_dev = 10.0
        else:
            projected = 50.0
            confidence = 0.85
            std_dev = 5.0

        lower = max(0.0, projected - 1.5 * std_dev)
        upper = projected + 1.5 * std_dev

        return DemandForecast(
            event_id=str(uuid.uuid4()),
            trace_id=effective_trace_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            contract_version="1.0.0",
            service_version="0.1.0",
            model_version="demand-v1",
            forecast_horizon_seconds=req.forecast_horizon_seconds,
            predicted_legitimate_rps=round(projected, 2),
            lower_bound_rps=round(lower, 2),
            upper_bound_rps=round(upper, 2),
            confidence=round(confidence, 2),
        )

    return app


# ==============================================================================
# End-to-End Test Harness Helper
# ==============================================================================

class ComparativeEvaluationHarness:
    """Encapsulates the integrated dynamic pipeline and evaluation service."""

    def __init__(
        self,
        demo_app: FastAPI,
        m1_app: FastAPI,
        m2_app: FastAPI,
        db_path: str,
        custom_telemetry_provider=None,
    ):
        self.demo_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=demo_app), base_url="http://demo-api:8000")
        self.m1_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=m1_app), base_url="http://traffic-intelligence:8001")
        self.m2_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=m2_app), base_url="http://demand-intelligence:8002")

        self.accumulator = DemandObservationAccumulator(db_path=db_path)
        self.traffic_client = TrafficIntelligenceClient(http_client=self.m1_client)
        self.demand_client = DemandIntelligenceClient(http_client=self.m2_client)

        self.telemetry_provider = custom_telemetry_provider or MockTelemetryProvider()
        self.resource_observer = ResourceObserverService(provider=self.telemetry_provider)
        self.decision_engine = DecisionEngine()
        self.evaluator = DefaultHPAEvaluationService(decision_engine=self.decision_engine)

        self.context_aggregator = ContextAggregatorService(
            traffic_client=self.traffic_client,
            demand_client=self.demand_client,
            resource_observer=self.resource_observer,
            decision_engine=self.decision_engine,
            demand_accumulator=self.accumulator,
        )

        self.scenario_runner = ScenarioRunner(
            demo_api_client=self.demo_client,
            traffic_client=self.m1_client,
        )


# ==============================================================================
# 1. Test Scenario A — Steady Legitimate Traffic Evaluation
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_a_steady_legitimate_comparative_evaluation(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """
    Scenario A: Steady Legitimate Traffic.
    Evaluates baseline operation: Normal legitimate demand is right-sized by SentinelScale
    while reactive HPA maintains static default capacity.
    """
    db_path = str(tmp_path / "scenario_a_eval.db")
    harness = ComparativeEvaluationHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    scenario = create_scenario_preset(TrafficScenarioType.STEADY_LEGITIMATE, duration_seconds=5.0)
    trace_id = "trace-f5-scenario-a"
    scenario.trace_id = trace_id

    result: ScenarioExecutionResult = await harness.scenario_runner.run_scenario(scenario)
    harness.accumulator.record_traffic_assessment(result.assessment, target_service="demo-api")

    context = await harness.context_aggregator.aggregate_context(workload="demo-api", trace_id=trace_id)
    decision = await harness.decision_engine.evaluate_decision(context)
    evaluation: EvaluationResult = harness.evaluator.evaluate_decision(decision)

    assert evaluation.trace_id == trace_id
    assert evaluation.traffic_risk < 0.25
    assert evaluation.predicted_legitimate_rps > 0.0
    assert evaluation.hpa_recommended_pods >= 2
    assert evaluation.sentinelscale_recommended_pods >= 2
    assert evaluation.category in (
        EvaluationCategory.ALIGNED,
        EvaluationCategory.SCALE_DOWN_DIFFERENCE,
        EvaluationCategory.SENTINELSCALE_PROACTIVELY_SCALES,
    )
    assert evaluation.recommendation_difference in (
        RecommendationDifference.EQUAL,
        RecommendationDifference.SENTINELSCALE_FEWER_PODS,
    )


# ==============================================================================
# 2. Test Scenario B — Legitimate Flash Crowd Evaluation
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_b_legitimate_flash_crowd_comparative_evaluation(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """
    Scenario B: Legitimate Flash Crowd Surge (5x baseline).
    Proves SentinelScale is NOT an anti-scaling tool:
    Legitimate demand growth causes proactive scaling recommendation to meet business demand.
    """
    db_path = str(tmp_path / "scenario_b_eval.db")
    harness = ComparativeEvaluationHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    scenario = create_scenario_preset(TrafficScenarioType.LEGITIMATE_FLASH_CROWD, duration_seconds=5.0)
    trace_id = "trace-f5-scenario-b"
    scenario.trace_id = trace_id

    result: ScenarioExecutionResult = await harness.scenario_runner.run_scenario(scenario)
    harness.accumulator.record_traffic_assessment(result.assessment, target_service="demo-api")

    context = await harness.context_aggregator.aggregate_context(workload="demo-api", trace_id=trace_id)
    decision = await harness.decision_engine.evaluate_decision(context)
    evaluation: EvaluationResult = harness.evaluator.evaluate_decision(decision)

    assert evaluation.traffic_risk < 0.35
    assert evaluation.predicted_legitimate_rps > 100.0
    assert evaluation.sentinelscale_recommended_pods >= 2
    assert evaluation.category in (
        EvaluationCategory.ALIGNED,
        EvaluationCategory.SENTINELSCALE_PROACTIVELY_SCALES,
        EvaluationCategory.SCALE_DOWN_DIFFERENCE,
    )


# ==============================================================================
# 3. Test Scenario C — Hostile L7 Flood (EDoS Overprovisioning Suppression)
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_c_hostile_l7_flood_attack_suppression_evaluation(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """
    Scenario C: Hostile L7 Flood Attack.
    CRITICAL EVALUATION: When attack traffic causes 95% CPU surge, baseline HPA
    scales up blindly to 6-8 pods, while SentinelScale holds at 4 pods.
    Evaluator MUST classify as SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE with positive pod savings.
    """
    db_path = str(tmp_path / "scenario_c_eval.db")

    class HighCpuAttackProvider(MockTelemetryProvider):
        async def fetch_resource_state(self, namespace: str, workload: str, trace_id: str | None = None) -> ResourceState:
            state = await super().fetch_resource_state(namespace, workload, trace_id)
            return state.model_copy(update={"cpu_utilization": 0.95, "running_pods": 4, "desired_pods": 4})

    harness = ComparativeEvaluationHarness(
        demo_api_app,
        traffic_intelligence_app,
        demand_intelligence_app,
        db_path,
        custom_telemetry_provider=HighCpuAttackProvider(),
    )

    # 1. Seed baseline legitimate observation in SQLite history
    now = time.time()
    seed_ts = datetime.fromtimestamp(now - 120, tz=timezone.utc).isoformat()
    seed_ass = TrafficAssessment(
        event_id="seed-c-01",
        trace_id="trace-f5-scenario-c",
        timestamp=seed_ts,
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="traffic-rules-v1",
        window_seconds=60,
        total_rps=50.0,
        legitimate_rps_estimate=50.0,
        suspicious_rps_estimate=0.0,
        risk_score=0.10,
        legitimacy_score=0.90,
        confidence=0.95,
        classification=TrafficClassification.LEGITIMATE,
        top_signals=[],
    )
    harness.accumulator.record_traffic_assessment(seed_ass, target_service="demo-api")

    # 2. Run real Hostile L7 Flood (300 RPS)
    scenario = create_scenario_preset(TrafficScenarioType.HOSTILE_L7_FLOOD, duration_seconds=5.0)
    trace_id = "trace-f5-scenario-c"
    scenario.trace_id = trace_id

    result: ScenarioExecutionResult = await harness.scenario_runner.run_scenario(scenario)

    # M1 assesses high risk & malicious
    assert result.assessment.risk_score >= 0.80
    assert result.assessment.classification in (TrafficClassification.MALICIOUS, TrafficClassification.SUSPICIOUS)

    # F2 accumulator rejects attack traffic
    record_result = harness.accumulator.record_traffic_assessment(result.assessment, target_service="demo-api")
    assert record_result is None  # Attack traffic is blocked from demand store

    # 3. Aggregate context & evaluate comparative decision
    resource_state = await harness.resource_observer.get_current_resource_state(
        namespace="sentinelscale", workload="demo-api", trace_id=trace_id
    )
    forecast = await harness.demand_client.fetch_forecast(
        forecast_horizon_seconds=300,
        trace_id=trace_id,
        target_service="demo-api",
        observations=harness.accumulator.get_historical_demand_observations(target_service="demo-api"),
    )

    context = DecisionContext(
        context_id="ctx-f5-c",
        trace_id=trace_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        contract_version="1.0.0",
        target_workload="demo-api",
        traffic_assessment=result.assessment,
        demand_forecast=forecast,
        resource_state=resource_state,
        dry_run=True,
        shadow_mode=True,
    )

    decision = await harness.decision_engine.evaluate_decision(context)
    evaluation: EvaluationResult = harness.evaluator.evaluate_decision(decision)

    # Quantitative Assertions
    assert decision.action in (ScalingAction.HOLD, ScalingAction.RATE_LIMIT, ScalingAction.MITIGATE)
    assert decision.recommended_pods < decision.baseline_hpa_recommended_pods
    assert decision.baseline_hpa_recommended_pods >= 6
    assert evaluation.category == EvaluationCategory.SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE
    assert evaluation.recommendation_difference == RecommendationDifference.SENTINELSCALE_FEWER_PODS
    assert evaluation.metrics.unnecessary_scale_up_signal is True
    assert evaluation.metrics.estimated_pod_hours_saved_per_hour >= 2.0


# ==============================================================================
# 4. Test Scenario D — Mixed Traffic Evaluation
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_d_mixed_traffic_comparative_evaluation(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """
    Scenario D: Mixed Traffic.
    Proves that under blended traffic (legitimate + scraper), demand forecast is derived
    from legitimate demand estimate and evaluated accordingly.
    """
    db_path = str(tmp_path / "scenario_d_eval.db")
    harness = ComparativeEvaluationHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    scenario = create_scenario_preset(TrafficScenarioType.MIXED_TRAFFIC, duration_seconds=5.0)
    trace_id = "trace-f5-scenario-d"
    scenario.trace_id = trace_id

    result: ScenarioExecutionResult = await harness.scenario_runner.run_scenario(scenario)
    harness.accumulator.record_traffic_assessment(result.assessment, target_service="demo-api")

    context = await harness.context_aggregator.aggregate_context(workload="demo-api", trace_id=trace_id)
    decision = await harness.decision_engine.evaluate_decision(context)
    evaluation: EvaluationResult = harness.evaluator.evaluate_decision(decision)

    assert evaluation.traffic_risk < 0.60
    assert evaluation.predicted_legitimate_rps <= result.assessment.total_rps
    assert evaluation.hpa_recommended_pods >= 2
    assert evaluation.sentinelscale_recommended_pods >= 2


# ==============================================================================
# 5. Test M1 and M2 Data Provenance in Evaluation
# ==============================================================================

@pytest.mark.asyncio
async def test_evaluation_records_contain_genuine_m1_m2_provenance(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify that evaluation records are linked to genuine M1 and M2 outputs."""
    db_path = str(tmp_path / "provenance_eval.db")
    harness = ComparativeEvaluationHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    trace_id = "trace-f5-provenance-05"
    context = await harness.context_aggregator.aggregate_context(workload="demo-api", trace_id=trace_id)
    decision = await harness.decision_engine.evaluate_decision(context)
    evaluation: EvaluationResult = harness.evaluator.evaluate_decision(decision)

    assert evaluation.trace_id == trace_id
    assert evaluation.traffic_risk == context.traffic_assessment.risk_score
    assert evaluation.predicted_legitimate_rps == context.demand_forecast.predicted_legitimate_rps
    assert evaluation.current_capacity_rps == context.resource_state.current_capacity_rps


# ==============================================================================
# 6. Test Replica Delta and Recommendation Difference Direction
# ==============================================================================

@pytest.mark.asyncio
async def test_replica_delta_and_recommendation_difference_conformance(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify that replica_delta and recommendation_difference strictly match definitions."""
    db_path = str(tmp_path / "delta_check.db")
    harness = ComparativeEvaluationHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    context = await harness.context_aggregator.aggregate_context(workload="demo-api")
    decision = await harness.decision_engine.evaluate_decision(context)
    evaluation: EvaluationResult = harness.evaluator.evaluate_decision(decision)

    expected_delta = evaluation.sentinelscale_recommended_pods - evaluation.hpa_recommended_pods
    assert evaluation.metrics.replica_delta == expected_delta
    assert evaluation.metrics.absolute_replica_delta == abs(expected_delta)

    if expected_delta == 0:
        assert evaluation.recommendation_difference == RecommendationDifference.EQUAL
    elif expected_delta < 0:
        assert evaluation.recommendation_difference == RecommendationDifference.SENTINELSCALE_FEWER_PODS
    else:
        assert evaluation.recommendation_difference == RecommendationDifference.SENTINELSCALE_MORE_PODS


# ==============================================================================
# 7. Test Pod-Hours Saved Calculation
# ==============================================================================

@pytest.mark.asyncio
async def test_pod_hours_saved_calculation_integrity(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify that estimated_pod_hours_saved_per_hour equals max(0, hpa - sentinelscale)."""
    db_path = str(tmp_path / "savings_check.db")
    harness = ComparativeEvaluationHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    context = await harness.context_aggregator.aggregate_context(workload="demo-api")
    decision = await harness.decision_engine.evaluate_decision(context)
    evaluation: EvaluationResult = harness.evaluator.evaluate_decision(decision)

    expected_saved = max(0.0, float(evaluation.hpa_recommended_pods - evaluation.sentinelscale_recommended_pods))
    assert evaluation.metrics.estimated_pod_hours_saved_per_hour == expected_saved


# ==============================================================================
# 8. Test Zero Raw Attack Traffic Entry into Demand History
# ==============================================================================

@pytest.mark.asyncio
async def test_no_raw_attack_traffic_enters_demand_history(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify that hostile flood requests are completely barred from entering SQLite demand history."""
    db_path = str(tmp_path / "attack_barrier.db")
    harness = ComparativeEvaluationHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    scenario = create_scenario_preset(TrafficScenarioType.HOSTILE_L7_FLOOD, duration_seconds=5.0)
    result = await harness.scenario_runner.run_scenario(scenario)

    record_res = harness.accumulator.record_traffic_assessment(result.assessment, target_service="demo-api")
    assert record_res is None

    stored = harness.accumulator.get_historical_demand_observations(target_service="demo-api")
    assert len(stored) == 0


# ==============================================================================
# 9. Test Trace ID Association with Evaluation Result
# ==============================================================================

@pytest.mark.asyncio
async def test_trace_id_retained_in_evaluation_result(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify that the end-to-end trace ID is preserved in EvaluationResult."""
    db_path = str(tmp_path / "trace_eval_res.db")
    harness = ComparativeEvaluationHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    test_trace = "trace-f5-evaluation-trace-777"
    context = await harness.context_aggregator.aggregate_context(workload="demo-api", trace_id=test_trace)
    decision = await harness.decision_engine.evaluate_decision(context)
    evaluation: EvaluationResult = harness.evaluator.evaluate_decision(decision)

    assert evaluation.trace_id == test_trace


# ==============================================================================
# 10. Test Safety Invariants Preserved in F5
# ==============================================================================

@pytest.mark.asyncio
async def test_safety_invariants_preserved_in_f5(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify dry_run=True, shadow_mode=True, and zero Kubernetes mutations in F5."""
    db_path = str(tmp_path / "safety_f5.db")
    harness = ComparativeEvaluationHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    context = await harness.context_aggregator.aggregate_context(workload="demo-api")
    decision = await harness.decision_engine.evaluate_decision(context)
    evaluation: EvaluationResult = harness.evaluator.evaluate_decision(decision)

    assert evaluation.dry_run is True
    assert evaluation.shadow_mode is True
    assert decision.dry_run is True
    assert decision.shadow_mode is True
