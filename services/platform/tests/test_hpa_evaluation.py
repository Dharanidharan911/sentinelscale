import os
import tempfile
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.main import app
from app.models.context import DecisionContext
from app.models.decision import ScalingAction
from app.models.demand_contract import DemandForecast
from app.models.evaluation import (
    EvaluationCategory,
    EvaluationResult,
    RecommendationDifference,
)
from app.models.history import StoredObservation
from app.models.resource import ResourceState
from app.models.traffic_contract import TrafficAssessment, TrafficClassification
from app.services.evaluation.evaluator import DefaultHPAEvaluationService
from app.services.evaluation.factory import get_evaluation_service
from app.services.history.sqlite_store import SQLiteDecisionHistoryStore
from tests.fixtures_decision import (
    make_decision_context,
    make_demand_forecast,
    make_resource_state,
    make_traffic_assessment,
)


# ------------------------------------------------------------------------------
# Unit Tests for Evaluation Logic
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluation_aligned_under_normal_conditions():
    """
    Test 1: Normal traffic conditions where HPA and SentinelScale recommendations are aligned.
    """
    # 4 pods * 350 RPS capacity/pod = 1400 RPS capacity. Demand = 1100 RPS.
    # CPU util = 0.70 (target 0.70) -> HPA: ceil(4 * (0.70 / 0.70)) = 4 pods.
    # SentinelScale: ceil(1100 / 350) = 4 pods.
    ctx = make_decision_context(
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.LEGITIMATE,
            risk_score=0.10,
            confidence=0.95,
        ),
        demand_forecast=make_demand_forecast(
            predicted_legitimate_rps=1100.0,
            confidence=0.95,
        ),
        resource_state=make_resource_state(
            running_pods=4,
            cpu_utilization=0.70,
            current_capacity_rps=1400.0,
        ),
    )
    evaluator = DefaultHPAEvaluationService()
    result = await evaluator.evaluate_context(ctx)

    assert isinstance(result, EvaluationResult)
    assert result.category == EvaluationCategory.ALIGNED
    assert result.recommendation_difference == RecommendationDifference.EQUAL
    assert result.hpa_recommended_pods == 4
    assert result.sentinelscale_recommended_pods == 4
    assert result.metrics.replica_delta == 0
    assert result.metrics.absolute_replica_delta == 0
    assert result.metrics.estimated_pod_hours_saved_per_hour == 0.0
    assert not result.metrics.unnecessary_scale_up_signal
    assert result.metrics.capacity_satisfied is True
    assert result.dry_run is True
    assert result.shadow_mode is True


@pytest.mark.asyncio
async def test_evaluation_prevents_unnecessary_scale_during_attack():
    """
    Test 2: Suspicious/malicious traffic surge causing high CPU (0.95), where HPA scales out
    reactively to 6 pods, but SentinelScale suppresses scale-out because legitimate RPS is only 850 RPS (fits in 4 pods).
    """
    ctx = make_decision_context(
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.MALICIOUS,
            risk_score=0.92,
            confidence=0.95,
            total_rps=4000.0,
            legitimate_rps=850.0,
            suspicious_rps=3150.0,
        ),
        demand_forecast=make_demand_forecast(
            predicted_legitimate_rps=850.0,
            confidence=0.95,
        ),
        resource_state=make_resource_state(
            running_pods=4,
            cpu_utilization=0.95,  # HPA: ceil(4 * 0.95 / 0.70) = 6 pods
            current_capacity_rps=1400.0,
        ),
    )
    evaluator = DefaultHPAEvaluationService()
    result = await evaluator.evaluate_context(ctx)

    assert result.category == EvaluationCategory.SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE
    assert result.recommendation_difference == RecommendationDifference.SENTINELSCALE_FEWER_PODS
    assert result.hpa_recommended_pods > result.sentinelscale_recommended_pods
    assert result.metrics.unnecessary_scale_up_signal is True
    assert result.metrics.replica_delta < 0
    assert result.metrics.absolute_replica_delta == abs(result.metrics.replica_delta)
    assert result.metrics.estimated_pod_hours_saved_per_hour > 0
    assert result.metrics.suppression_reason is not None
    assert "High traffic risk" in result.metrics.suppression_reason
    assert "pod-hours/hr" in result.explanation


@pytest.mark.asyncio
async def test_evaluation_proactive_scaling_for_legitimate_demand():
    """
    Test 3: Legitimate demand surge (predicted 2800 RPS > 1400 RPS capacity) requiring proactive scale-out.
    """
    ctx = make_decision_context(
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.LEGITIMATE,
            risk_score=0.05,
            confidence=0.95,
            total_rps=2800.0,
            legitimate_rps=2800.0,
            suspicious_rps=0.0,
        ),
        demand_forecast=make_demand_forecast(
            predicted_legitimate_rps=2800.0,
            confidence=0.95,
        ),
        resource_state=make_resource_state(
            running_pods=4,
            cpu_utilization=0.50,
            current_capacity_rps=1400.0,
        ),
    )
    evaluator = DefaultHPAEvaluationService()
    result = await evaluator.evaluate_context(ctx)

    assert result.category == EvaluationCategory.SENTINELSCALE_PROACTIVELY_SCALES
    assert result.sentinelscale_recommended_pods >= 8
    assert result.metrics.capacity_satisfied is False
    assert result.metrics.unnecessary_scale_up_signal is False


@pytest.mark.asyncio
async def test_evaluation_scale_down_difference():
    """
    Test 4: Legitimate demand is substantially below capacity, triggering scale down difference.
    """
    ctx = make_decision_context(
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.LEGITIMATE,
            risk_score=0.10,
            confidence=0.90,
            total_rps=400.0,
            legitimate_rps=400.0,
            suspicious_rps=0.0,
        ),
        demand_forecast=make_demand_forecast(
            predicted_legitimate_rps=400.0,
            confidence=0.90,
        ),
        resource_state=make_resource_state(
            running_pods=6,
            cpu_utilization=0.68,  # HPA: ceil(6 * 0.68 / 0.70) = 6 pods
            current_capacity_rps=2100.0,
        ),
    )
    evaluator = DefaultHPAEvaluationService()
    result = await evaluator.evaluate_context(ctx)

    assert result.category in [
        EvaluationCategory.SCALE_DOWN_DIFFERENCE,
        EvaluationCategory.SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE,
    ]
    assert result.sentinelscale_recommended_pods < ctx.resource_state.running_pods


@pytest.mark.asyncio
async def test_evaluation_uncertain_low_confidence():
    """
    Test 5: Low confidence input signals trigger UNCERTAIN category.
    """
    ctx = make_decision_context(
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.SUSPICIOUS,
            risk_score=0.80,
            confidence=0.30,  # Low confidence
        ),
        demand_forecast=make_demand_forecast(
            predicted_legitimate_rps=800.0,
            confidence=0.40,  # Low confidence
        ),
        resource_state=make_resource_state(
            running_pods=4,
            cpu_utilization=0.85,
            current_capacity_rps=1400.0,
        ),
    )
    evaluator = DefaultHPAEvaluationService()
    result = await evaluator.evaluate_context(ctx)

    assert result.category == EvaluationCategory.UNCERTAIN
    assert "Low composite confidence" in result.explanation


# ------------------------------------------------------------------------------
# Stored Observation Evaluation Tests
# ------------------------------------------------------------------------------

def test_evaluate_observation_id_success():
    """
    Test evaluating directly from a stored observation record in SQLite store.
    """
    store = SQLiteDecisionHistoryStore(db_path=":memory:")
    obs_id = "obs-eval-stored-1"
    obs = StoredObservation(
        id=obs_id,
        trace_id="trace-eval-stored-1",
        timestamp=datetime.now(timezone.utc).isoformat(),
        success=True,
        action=ScalingAction.HOLD,
        reason="High traffic risk detected.",
        confidence=0.90,
        traffic_risk=0.85,
        predicted_legitimate_rps=60.0,
        current_capacity_rps=100.0,
        current_pods=2,
        recommended_pods=2,
        baseline_hpa_recommended_pods=5,
        pod_delta_vs_baseline=-3,
        policy="standard",
        dry_run=True,
        shadow_mode=True,
    )
    store.record_observation(obs)

    evaluator = DefaultHPAEvaluationService(history_store=store)
    result = evaluator.evaluate_observation_id(obs_id)

    assert result.category == EvaluationCategory.SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE
    assert result.hpa_recommended_pods == 5
    assert result.sentinelscale_recommended_pods == 2
    assert result.metrics.replica_delta == -3
    assert result.metrics.estimated_pod_hours_saved_per_hour == 3.0


def test_evaluate_observation_id_not_found():
    """
    Test that evaluating a non-existent observation ID raises ValueError.
    """
    store = SQLiteDecisionHistoryStore(db_path=":memory:")
    evaluator = DefaultHPAEvaluationService(history_store=store)
    with pytest.raises(ValueError, match="not found"):
        evaluator.evaluate_observation_id("non-existent-id")


# ------------------------------------------------------------------------------
# API Endpoints Integration Tests
# ------------------------------------------------------------------------------

def test_api_post_evaluate():
    """
    Test POST /api/v1/evaluation/evaluate endpoint with valid DecisionContext.
    """
    client = TestClient(app)
    ctx = make_decision_context(
        traffic_assessment=make_traffic_assessment(
            classification=TrafficClassification.MALICIOUS,
            risk_score=0.90,
            confidence=0.95,
            total_rps=4000.0,
            legitimate_rps=800.0,
            suspicious_rps=3200.0,
        ),
        demand_forecast=make_demand_forecast(
            predicted_legitimate_rps=800.0,
            confidence=0.95,
        ),
        resource_state=make_resource_state(
            running_pods=4,
            cpu_utilization=0.95,
            current_capacity_rps=1400.0,
        ),
    )
    resp = client.post("/api/v1/evaluation/evaluate", json=ctx.model_dump())
    assert resp.status_code == 200
    data = resp.json()

    assert data["category"] == "SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE"
    assert data["recommendation_difference"] == "SENTINELSCALE_FEWER_PODS"
    assert data["hpa_recommended_pods"] > data["sentinelscale_recommended_pods"]
    assert data["metrics"]["unnecessary_scale_up_signal"] is True
    assert data["metrics"]["estimated_pod_hours_saved_per_hour"] > 0
    assert data["dry_run"] is True
    assert data["shadow_mode"] is True


def test_api_get_hpa_vs_sentinelscale_latest():
    """
    Test GET /api/v1/evaluation/hpa-vs-sentinelscale retrieving latest observation.
    """
    client = TestClient(app)
    resp = client.get("/api/v1/evaluation/hpa-vs-sentinelscale")
    assert resp.status_code in [200, 404]
    if resp.status_code == 200:
        data = resp.json()
        assert "category" in data
        assert "metrics" in data
        assert "hpa_recommended_pods" in data
        assert "sentinelscale_recommended_pods" in data
