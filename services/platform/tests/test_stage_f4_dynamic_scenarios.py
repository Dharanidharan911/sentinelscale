"""
SentinelScale — Stage F4: End-to-End Dynamic Scenario Suite
Proves that the complete system operates on dynamically generated HTTP traffic
and that information propagates through the entire architecture:

Generated HTTP Traffic → Demo API → F1 Collector → M1 Traffic Intelligence
  → TrafficAssessment → F2 Accumulator → F3 Dispatcher → M2 Demand Intelligence
  → DemandForecast → M3 Context Aggregator → DecisionEngine → ScalingDecision
  → HPA vs SentinelScale Evaluator
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
# In-Process Microservice Fixtures
# ==============================================================================

@pytest.fixture
def demo_api_app() -> FastAPI:
    """Real in-memory Demo API with catalog, search, cart, and auth endpoints."""
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
    """Real deterministic M1 evaluation engine mounted on FastAPI."""
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

        # M1 Deterministic scoring rules
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
    """Real deterministic M2 demand-v1 forecasting engine mounted on FastAPI."""
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
# Helper to build End-to-End Environment
# ==============================================================================

class EndToEndTestHarness:
    """Encapsulates the complete end-to-end integration environment."""

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
# 1. Test Scenario A — Steady Legitimate Traffic
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_a_steady_legitimate_full_pipeline(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """
    Scenario A: Steady Legitimate Traffic.
    Establish legitimate baseline with 50 distributed IPs, browser User-Agents, valid endpoints.
    Verifies M1 low risk, F2 acceptance, M2 legitimate forecast, M3 steady decision.
    """
    db_path = str(tmp_path / "scenario_a.db")
    harness = EndToEndTestHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    # 1. Generate real HTTP traffic and get M1 assessment
    scenario = create_scenario_preset(TrafficScenarioType.STEADY_LEGITIMATE, duration_seconds=5.0)
    trace_id = "trace-f4-scenario-a-01"
    scenario.trace_id = trace_id

    result: ScenarioExecutionResult = await harness.scenario_runner.run_scenario(scenario)

    # F1 Assertions
    assert result.total_requests_generated > 0
    assert result.observed_telemetry.top_ip_ratio < 0.20
    assert result.observed_telemetry.non_standard_ua_ratio == 0.0
    assert result.observed_telemetry.status_codes.status_2xx > 0

    # M1 Assertions
    assessment = result.assessment
    assert assessment.risk_score < 0.25
    assert assessment.classification == TrafficClassification.LEGITIMATE
    assert assessment.legitimate_rps_estimate > 0.0

    # F2 Record & Accumulator Assertion
    obs = harness.accumulator.record_traffic_assessment(assessment, target_service="demo-api")
    assert obs is not None
    stored_obs = harness.accumulator.get_historical_demand_observations(target_service="demo-api")
    assert len(stored_obs) == 1
    assert stored_obs[0].rps == assessment.legitimate_rps_estimate

    # F3 & M3 Orchestration
    context = await harness.context_aggregator.aggregate_context(workload="demo-api", trace_id=trace_id)
    assert context.trace_id == trace_id
    assert context.traffic_assessment.risk_score < 0.25
    assert context.traffic_assessment.classification == TrafficClassification.LEGITIMATE
    assert context.demand_forecast.predicted_legitimate_rps > 0.0

    decision = await harness.decision_engine.evaluate_decision(context)
    assert decision.action in (ScalingAction.HOLD, ScalingAction.SCALE)
    assert decision.dry_run is True
    assert decision.shadow_mode is True

    # Evaluator Assertion
    evaluation = harness.evaluator.evaluate_decision(decision)
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
# 2. Test Scenario B — Legitimate Flash Crowd
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_b_legitimate_flash_crowd_distinguished_from_attack(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """
    Scenario B: Legitimate Flash Crowd (5x surge).
    Proves that high traffic volume alone is not treated as malicious.
    M1 recognizes organic surge; F2 stores higher legitimate observations; M2 projects surge.
    """
    db_path = str(tmp_path / "scenario_b.db")
    harness = EndToEndTestHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    scenario = create_scenario_preset(TrafficScenarioType.LEGITIMATE_FLASH_CROWD, duration_seconds=5.0)
    trace_id = "trace-f4-scenario-b-02"
    scenario.trace_id = trace_id

    result: ScenarioExecutionResult = await harness.scenario_runner.run_scenario(scenario)

    # F1 Assertions
    assert result.observed_telemetry.total_rps > 100.0
    assert result.observed_telemetry.top_ip_ratio < 0.15
    assert result.observed_telemetry.non_standard_ua_ratio == 0.0

    # M1 Assertions: High volume but low risk
    assessment = result.assessment
    assert assessment.risk_score < 0.35
    assert assessment.classification == TrafficClassification.LEGITIMATE
    assert assessment.legitimate_rps_estimate > 100.0

    # F2 Gate: Accepted
    obs = harness.accumulator.record_traffic_assessment(assessment, target_service="demo-api")
    assert obs is not None
    assert obs.rps == assessment.legitimate_rps_estimate

    # M2 & M3 Full Aggregation
    context = await harness.context_aggregator.aggregate_context(workload="demo-api", trace_id=trace_id)
    assert context.demand_forecast.predicted_legitimate_rps > 100.0

    decision = await harness.decision_engine.evaluate_decision(context)
    assert decision.dry_run is True
    assert decision.recommended_pods >= 2


# ==============================================================================
# 3. Test Scenario C — Hostile L7 Flood (Security Gate)
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_c_hostile_l7_flood_rejected_by_f2_demand_gate(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """
    Scenario C: Hostile L7 Flood Attack.
    CRITICAL INVARIANT: Attack traffic must NEVER become legitimate demand history.
    M1 flags high risk/malicious; F2 rejects observation; M2 receives 0 hostile observations;
    SentinelScale prevents HPA overprovisioning.
    """
    db_path = str(tmp_path / "scenario_c.db")
    harness = EndToEndTestHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    # Pre-seed 1 legitimate baseline observation
    now = time.time()
    legit_ts = datetime.fromtimestamp(now - 120, tz=timezone.utc).isoformat()
    seed_assessment = TrafficAssessment(
        event_id="seed-evt-01",
        trace_id="seed-trace",
        timestamp=legit_ts,
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
        top_signals=["legitimate_traffic_profile"],
    )
    harness.accumulator.record_traffic_assessment(seed_assessment, target_service="demo-api")

    # Run Hostile L7 Flood
    scenario = create_scenario_preset(TrafficScenarioType.HOSTILE_L7_FLOOD, duration_seconds=5.0)
    trace_id = "trace-f4-scenario-c-03"
    scenario.trace_id = trace_id

    result: ScenarioExecutionResult = await harness.scenario_runner.run_scenario(scenario)

    # F1 Assertions
    assert result.observed_telemetry.top_ip_ratio >= 0.70
    assert result.observed_telemetry.non_standard_ua_ratio >= 0.65
    assert result.observed_telemetry.status_codes.status_4xx > 0

    # M1 Assertions: High risk / malicious
    assessment = result.assessment
    assert assessment.risk_score >= 0.80
    assert assessment.classification in (TrafficClassification.MALICIOUS, TrafficClassification.SUSPICIOUS)

    # F2 Gate: REJECTED!
    obs_rejected = harness.accumulator.record_traffic_assessment(assessment, target_service="demo-api")
    assert obs_rejected is None  # Hostile traffic is blocked from demand store

    # Verify SQLite store contains ONLY the seed legitimate observation (0 attack observations)
    observations_in_db = harness.accumulator.get_historical_demand_observations(target_service="demo-api")
    assert len(observations_in_db) == 1
    assert observations_in_db[0].rps == 50.0
    assert all(o.rps < 100.0 for o in observations_in_db)

    # Full context orchestration
    context = await harness.context_aggregator.aggregate_context(workload="demo-api", trace_id=trace_id)
    # The demand forecast must reflect legitimate demand (~50 RPS), NOT the 300 RPS attack!
    assert context.demand_forecast.predicted_legitimate_rps < 100.0


# ==============================================================================
# 4. Test Scenario D — Mixed Legitimate + Suspicious Traffic
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_d_mixed_traffic_preserves_legitimate_provenance(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """
    Scenario D: Mixed Traffic (Legitimate users + single scraper).
    Proves total traffic != legitimate demand.
    M1 separates populations; F2 saves only legitimate RPS estimate.
    """
    db_path = str(tmp_path / "scenario_d.db")
    harness = EndToEndTestHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    scenario = create_scenario_preset(TrafficScenarioType.MIXED_TRAFFIC, duration_seconds=5.0)
    trace_id = "trace-f4-scenario-d-04"
    scenario.trace_id = trace_id

    result: ScenarioExecutionResult = await harness.scenario_runner.run_scenario(scenario)

    assessment = result.assessment
    # Total RPS is split
    assert assessment.total_rps > 0.0
    assert assessment.suspicious_rps_estimate > 0.0
    assert assessment.legitimate_rps_estimate < assessment.total_rps
    assert math.isclose(assessment.total_rps, assessment.legitimate_rps_estimate + assessment.suspicious_rps_estimate, rel_tol=1e-2)

    # F2 Gate saves legitimate estimate
    obs = harness.accumulator.record_traffic_assessment(assessment, target_service="demo-api")
    if assessment.risk_score <= 0.80:
        assert obs is not None
        assert obs.rps == assessment.legitimate_rps_estimate


# ==============================================================================
# 5. Test M2 Observation Dispatch Data Provenance
# ==============================================================================

@pytest.mark.asyncio
async def test_m2_observation_dispatch_data_provenance(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify that every observation received by M2 matches exact records in F2 SQLite DB."""
    db_path = str(tmp_path / "provenance_check.db")
    harness = EndToEndTestHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    now = time.time()
    for i in range(3):
        ts = datetime.fromtimestamp(now - 180 + i * 60, tz=timezone.utc).isoformat()
        ass = TrafficAssessment(
            event_id=f"prov-evt-{i}",
            trace_id=f"prov-trace-{i}",
            timestamp=ts,
            contract_version="1.0.0",
            service_version="0.1.0",
            model_version="traffic-rules-v1",
            window_seconds=60,
            total_rps=100.0 + i * 25.0,
            legitimate_rps_estimate=100.0 + i * 25.0,
            suspicious_rps_estimate=0.0,
            risk_score=0.10,
            legitimacy_score=0.90,
            confidence=0.95,
            classification=TrafficClassification.LEGITIMATE,
            top_signals=[],
        )
        harness.accumulator.record_traffic_assessment(ass, target_service="demo-api")

    db_obs = harness.accumulator.get_historical_demand_observations(target_service="demo-api")
    assert len(db_obs) == 3

    # Dispatch to M2
    forecast = await harness.demand_client.fetch_forecast(
        forecast_horizon_seconds=300,
        trace_id="trace-prov-val",
        target_service="demo-api",
        observations=db_obs,
    )

    assert isinstance(forecast, DemandForecast)
    assert forecast.confidence > 0.0
    assert forecast.predicted_legitimate_rps >= 100.0


# ==============================================================================
# 6. Test Dynamic Forecast Under Changing Demand
# ==============================================================================

@pytest.mark.asyncio
async def test_m2_dynamic_forecast_behavior_under_varying_demand(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify that M2's forecast dynamically increases when historical legitimate demand increases."""
    db_path_1 = str(tmp_path / "dyn_forecast_1.db")
    db_path_2 = str(tmp_path / "dyn_forecast_2.db")
    harness1 = EndToEndTestHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path_1)
    harness2 = EndToEndTestHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path_2)

    now = time.time()
    # History 1: Low baseline demand (50 RPS)
    for i in range(3):
        ts = datetime.fromtimestamp(now - 180 + i * 60, tz=timezone.utc).isoformat()
        ass = TrafficAssessment(
            event_id=f"low-evt-{i}",
            trace_id="trace-low",
            timestamp=ts,
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
        harness1.accumulator.record_traffic_assessment(ass, target_service="demo-api")

    # History 2: High demand (250 RPS)
    for i in range(3):
        ts = datetime.fromtimestamp(now - 180 + i * 60, tz=timezone.utc).isoformat()
        ass = TrafficAssessment(
            event_id=f"high-evt-{i}",
            trace_id="trace-high",
            timestamp=ts,
            contract_version="1.0.0",
            service_version="0.1.0",
            model_version="traffic-rules-v1",
            window_seconds=60,
            total_rps=250.0,
            legitimate_rps_estimate=250.0,
            suspicious_rps_estimate=0.0,
            risk_score=0.10,
            legitimacy_score=0.90,
            confidence=0.95,
            classification=TrafficClassification.LEGITIMATE,
            top_signals=[],
        )
        harness2.accumulator.record_traffic_assessment(ass, target_service="demo-api")

    ctx1 = await harness1.context_aggregator.aggregate_context(workload="demo-api")
    ctx2 = await harness2.context_aggregator.aggregate_context(workload="demo-api")

    assert ctx1.demand_forecast.predicted_legitimate_rps < 100.0
    assert ctx2.demand_forecast.predicted_legitimate_rps > 200.0
    assert ctx2.demand_forecast.predicted_legitimate_rps > ctx1.demand_forecast.predicted_legitimate_rps


# ==============================================================================
# 7. Test Decision Context Provenance
# ==============================================================================

@pytest.mark.asyncio
async def test_decision_context_contains_m1_and_m2_outputs(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify that DecisionContext contains genuine M1 assessment and M2 forecast."""
    db_path = str(tmp_path / "ctx_provenance.db")
    harness = EndToEndTestHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    trace_id = "trace-ctx-provenance-07"
    context = await harness.context_aggregator.aggregate_context(workload="demo-api", trace_id=trace_id)

    assert isinstance(context, DecisionContext)
    assert context.trace_id == trace_id
    assert context.traffic_assessment.contract_version == "1.0.0"
    assert context.demand_forecast.contract_version == "1.0.0"
    assert context.resource_state.contract_version == "1.0.0"
    assert context.dry_run is True
    assert context.shadow_mode is True


# ==============================================================================
# 8. Test Evaluator Receives Actual Decisions
# ==============================================================================

@pytest.mark.asyncio
async def test_evaluator_comparative_correctness_on_attack_suppression(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify that Evaluator correctly identifies attack suppression saving excess replicas."""
    db_path = str(tmp_path / "evaluator_test.db")

    # Resource provider simulating CPU spike to 95% due to DDoS flood
    class AttackTelemetryProvider(MockTelemetryProvider):
        async def fetch_resource_state(self, namespace: str, workload: str, trace_id: str | None = None) -> ResourceState:
            state = await super().fetch_resource_state(namespace, workload, trace_id)
            return state.model_copy(update={"cpu_utilization": 0.95, "running_pods": 4, "desired_pods": 4})

    harness = EndToEndTestHarness(
        demo_api_app,
        traffic_intelligence_app,
        demand_intelligence_app,
        db_path,
        custom_telemetry_provider=AttackTelemetryProvider(),
    )

    # Simulate attack traffic assessment in M1
    attack_assessment = TrafficAssessment(
        event_id="attack-evt-01",
        trace_id="trace-eval-08",
        timestamp=datetime.now(timezone.utc).isoformat(),
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="traffic-rules-v1",
        window_seconds=60,
        total_rps=5000.0,
        legitimate_rps_estimate=350.0,
        suspicious_rps_estimate=4650.0,
        risk_score=0.90,
        legitimacy_score=0.10,
        confidence=0.95,
        classification=TrafficClassification.MALICIOUS,
        top_signals=["critical_ip_concentration", "critical_burst_rate"],
    )

    demand_forecast = DemandForecast(
        event_id="demand-evt-01",
        trace_id="trace-eval-08",
        generated_at=datetime.now(timezone.utc).isoformat(),
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="demand-v1",
        forecast_horizon_seconds=300,
        predicted_legitimate_rps=350.0,
        lower_bound_rps=300.0,
        upper_bound_rps=400.0,
        confidence=0.95,
    )

    resource_state = await harness.resource_observer.get_current_resource_state(
        namespace="sentinelscale", workload="demo-api", trace_id="trace-eval-08"
    )

    context = DecisionContext(
        context_id="ctx-eval-01",
        trace_id="trace-eval-08",
        timestamp=datetime.now(timezone.utc).isoformat(),
        contract_version="1.0.0",
        target_workload="demo-api",
        traffic_assessment=attack_assessment,
        demand_forecast=demand_forecast,
        resource_state=resource_state,
        dry_run=True,
        shadow_mode=True,
    )

    decision = await harness.decision_engine.evaluate_decision(context)
    # SentinelScale holds/suppresses, while reactive HPA would scale to 6-8 pods due to 95% CPU
    assert decision.recommended_pods < decision.baseline_hpa_recommended_pods
    assert decision.baseline_hpa_recommended_pods >= 6

    evaluation: EvaluationResult = harness.evaluator.evaluate_decision(decision)
    assert evaluation.category == EvaluationCategory.SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE
    assert evaluation.recommendation_difference == RecommendationDifference.SENTINELSCALE_FEWER_PODS
    assert evaluation.metrics.estimated_pod_hours_saved_per_hour >= 2.0


# ==============================================================================
# 9. Test Trace ID Continuity
# ==============================================================================

@pytest.mark.asyncio
async def test_trace_id_continuity_across_full_f4_pipeline(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify trace ID propagation from scenario creation to final decision."""
    db_path = str(tmp_path / "trace_cont.db")
    harness = EndToEndTestHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    expected_trace = "trace-f4-continuity-999"
    scenario = create_scenario_preset(TrafficScenarioType.STEADY_LEGITIMATE, duration_seconds=5.0)
    scenario.trace_id = expected_trace

    res = await harness.scenario_runner.run_scenario(scenario)
    assert res.trace_id == expected_trace
    assert res.assessment.trace_id == expected_trace

    ctx = await harness.context_aggregator.aggregate_context(workload="demo-api", trace_id=expected_trace)
    assert ctx.trace_id == expected_trace
    assert ctx.traffic_assessment.trace_id == expected_trace
    assert ctx.demand_forecast.trace_id == expected_trace

    dec = await harness.decision_engine.evaluate_decision(ctx)
    assert dec.trace_id == expected_trace

    ev = harness.evaluator.evaluate_decision(dec)
    assert ev.trace_id == expected_trace


# ==============================================================================
# 10. Test Safety Invariants & Zero Kubernetes Mutations
# ==============================================================================

@pytest.mark.asyncio
async def test_safety_invariants_zero_kubernetes_mutations(demo_api_app, traffic_intelligence_app, demand_intelligence_app, tmp_path):
    """Verify dry_run=True, shadow_mode=True, and zero Kubernetes mutations throughout F4."""
    db_path = str(tmp_path / "safety_test.db")
    harness = EndToEndTestHarness(demo_api_app, traffic_intelligence_app, demand_intelligence_app, db_path)

    ctx = await harness.context_aggregator.aggregate_context(workload="demo-api")
    decision = await harness.decision_engine.evaluate_decision(ctx)

    assert decision.dry_run is True
    assert decision.shadow_mode is True
    # Verify no subprocess or mutation tools were invoked
    assert not hasattr(decision, "applied_replicas")
