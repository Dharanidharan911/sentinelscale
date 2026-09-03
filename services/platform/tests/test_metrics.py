import time
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.decision import ScalingAction, ScalingDecision
from app.services.context_aggregator import AggregationError, ContextAggregatorService
from app.services.metrics.prometheus import PrometheusMetricsService, normalize_error, normalize_reason
from app.services.observation_scheduler import ObservationSchedulerService


def make_mock_decision(
    action=ScalingAction.HOLD,
    recommended_pods=4,
    baseline_hpa_recommended_pods=6,
    pod_delta_vs_baseline=-2,
    traffic_risk=0.85,
    predicted_legitimate_rps=1200.0,
    current_capacity_rps=1400.0,
    current_pods=4,
    reason="Attack surge detected; suppressing wasteful scale-out",
):
    return ScalingDecision(
        decision_id="dec-metrics-01",
        event_id="evt-metrics-01",
        trace_id="trace-metrics-test",
        timestamp="2026-09-04T00:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="policy-rules-v0",
        action=action,
        reason=reason,
        confidence=0.94,
        traffic_risk=traffic_risk,
        predicted_legitimate_rps=predicted_legitimate_rps,
        current_capacity_rps=current_capacity_rps,
        current_pods=current_pods,
        recommended_pods=recommended_pods,
        baseline_hpa_recommended_pods=baseline_hpa_recommended_pods,
        pod_delta_vs_baseline=pod_delta_vs_baseline,
        policy="default-safe-guardrail-v1",
        dry_run=True,
        shadow_mode=True,
    )


# ==============================================================================
# 1. Normalization & Low-Cardinality Label Tests
# ==============================================================================

def test_normalization_reason_taxonomy():
    """Verify reasons are mapped to bounded low-cardinality categories."""
    assert normalize_reason("DDoS attack surge detected") == "ATTACK_MITIGATION"
    assert normalize_reason("Legitimate demand surge detected") == "LEGITIMATE_DEMAND_SURGE"
    assert normalize_reason("Low demand observed; scale down eligible") == "DEMAND_SCALE_DOWN"
    assert normalize_reason("Current capacity is sufficient") == "CAPACITY_SUFFICIENT"
    assert normalize_reason("Step-up surge limit clamped replicas") == "POLICY_CLAMPED"
    assert normalize_reason("Arbitrary unknown reason") == "OTHER"
    assert normalize_reason(None) == "OTHER"


def test_normalization_error_taxonomy():
    """Verify arbitrary error strings map to bounded low-cardinality categories."""
    assert normalize_error("TimeoutError", "Request timed out after 5.0s") == "timeout"
    assert normalize_error("HTTPStatusError", "502 Bad Gateway") == "bad_gateway"
    assert normalize_error("ConnectError", "Connection refused") == "connection_error"
    assert normalize_error("ValidationError", "Schema validation failed") == "schema_validation"
    assert normalize_error("TelemetryProviderError", "Prometheus down") == "telemetry_error"
    assert normalize_error("InternalError", "HTTP 500 server error") == "internal_error"
    assert normalize_error("UnknownException", "something weird") == "unknown"


# ==============================================================================
# 2. Prometheus Metrics Service Unit Tests
# ==============================================================================

def test_metrics_service_initialization_and_empty_export():
    """Verify metrics initialization emits valid Prometheus metadata comments."""
    service = PrometheusMetricsService()
    text = service.export_prometheus_text()

    assert "# HELP sentinelscale_observations_total" in text
    assert "# TYPE sentinelscale_observations_total counter"
    assert 'sentinelscale_observations_total{status="success"} 0.0' in text
    assert 'sentinelscale_observations_total{status="failure"} 0.0' in text
    assert "sentinelscale_scheduler_running 0.0" in text


def test_metrics_service_record_success():
    """Verify recording a successful evaluation updates counters, gauges, and histograms."""
    service = PrometheusMetricsService()
    decision = make_mock_decision(
        action=ScalingAction.HOLD,
        recommended_pods=4,
        baseline_hpa_recommended_pods=6,
        pod_delta_vs_baseline=-2,
        traffic_risk=0.88,
        predicted_legitimate_rps=1000.0,
        current_capacity_rps=1400.0,
        current_pods=4,
    )

    service.record_observation_success(decision, duration_s=0.15)
    text = service.export_prometheus_text()

    # 1. Observation counter
    assert 'sentinelscale_observations_total{status="success"} 1.0' in text

    # 2. Decision counter
    assert 'sentinelscale_decisions_total{action="HOLD"} 1.0' in text

    # 3. Decision reasons
    assert 'sentinelscale_decision_reasons_total{reason_category="ATTACK_MITIGATION"} 1.0' in text

    # 4. Latency histogram
    assert 'sentinelscale_evaluation_duration_seconds_bucket{le="0.25"} 1' in text
    assert "sentinelscale_evaluation_duration_seconds_count 1" in text

    # 5. Baseline HPA comparison gauges (signed divergence)
    assert "sentinelscale_sentinelscale_recommendation_pods 4.0" in text
    assert "sentinelscale_baseline_hpa_recommendation_pods 6.0" in text
    assert "sentinelscale_baseline_hpa_divergence_pods -2.0" in text

    # 6. Demand / Traffic gauges
    assert "sentinelscale_traffic_risk 0.88" in text
    assert "sentinelscale_predicted_legitimate_rps 1000.0" in text
    assert "sentinelscale_current_capacity_rps 1400.0" in text
    assert "sentinelscale_current_pods 4.0" in text
    assert "sentinelscale_recommended_pods 4.0" in text


def test_metrics_service_record_failure():
    """Verify recording an evaluation failure updates failure metrics."""
    service = PrometheusMetricsService()
    service.record_observation_failure(service="traffic", error_type="502 Bad Gateway", duration_s=0.08)
    text = service.export_prometheus_text()

    assert 'sentinelscale_observations_total{status="failure"} 1.0' in text
    assert 'sentinelscale_upstream_failures_total{error_type="bad_gateway",service="traffic"} 1.0' in text
    assert "sentinelscale_evaluation_duration_seconds_count 1" in text


def test_metrics_service_scheduler_and_history_events():
    """Verify scheduler health and history write/cleanup metrics."""
    service = PrometheusMetricsService()

    service.set_scheduler_running(True)
    service.record_scheduler_skipped()
    service.record_history_write(success=True)
    service.record_history_write(success=False)
    service.record_history_cleanup(count=12)

    text = service.export_prometheus_text()

    assert "sentinelscale_scheduler_running 1.0" in text
    assert "sentinelscale_scheduler_observations_skipped_total 1.0" in text
    assert 'sentinelscale_history_records_total{status="success"} 1.0' in text
    assert 'sentinelscale_history_records_total{status="failure"} 1.0' in text
    assert "sentinelscale_history_write_failures_total 1.0" in text
    assert "sentinelscale_history_cleanup_total 12.0" in text


def test_metrics_service_cardinality_guarantee():
    """Verify that high-cardinality values like trace_ids or random UUIDs never appear in metric labels."""
    service = PrometheusMetricsService()
    decision = make_mock_decision()

    service.record_observation_success(decision, duration_s=0.05)
    text = service.export_prometheus_text()

    assert "trace-metrics-test" not in text
    assert "dec-metrics-01" not in text
    assert "evt-metrics-01" not in text


# ==============================================================================
# 3. Scheduler & Metrics Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_scheduler_updates_metrics_on_cycle():
    """Verify ObservationScheduler updates metrics on both success and failure cycles."""
    metrics_service = PrometheusMetricsService()
    mock_aggregator = MagicMock(spec=ContextAggregatorService)

    # 1. Successful cycle
    decision = make_mock_decision(action=ScalingAction.SCALE, recommended_pods=8)
    mock_aggregator.orchestrate_decision = AsyncMock(return_value=decision)

    scheduler = ObservationSchedulerService(
        aggregator=mock_aggregator,
        metrics=metrics_service,
        interval_seconds=1.0,
    )

    await scheduler.start()
    res1 = await scheduler.execute_evaluation(trace_id="tr-sched-m1")
    assert res1.success is True

    text1 = metrics_service.export_prometheus_text()
    assert 'sentinelscale_observations_total{status="success"} 1.0' in text1
    assert 'sentinelscale_decisions_total{action="SCALE"} 1.0' in text1
    assert "sentinelscale_scheduler_running 1.0" in text1

    # 2. Failing cycle
    mock_aggregator.orchestrate_decision = AsyncMock(
        side_effect=AggregationError("Demand Intelligence", "Request timed out")
    )
    res2 = await scheduler.execute_evaluation(trace_id="tr-sched-m2")
    assert res2.success is False

    text2 = metrics_service.export_prometheus_text()
    assert 'sentinelscale_observations_total{status="failure"} 1.0' in text2
    assert 'sentinelscale_upstream_failures_total{error_type="timeout",service="demand_intelligence"} 1.0' in text2

    await scheduler.stop()
    text3 = metrics_service.export_prometheus_text()
    assert "sentinelscale_scheduler_running 0.0" in text3


# ==============================================================================
# 4. HTTP GET /metrics Endpoint Tests
# ==============================================================================

client = TestClient(app)


def test_get_metrics_endpoint_returns_200_and_prometheus_format():
    """Test GET /metrics returns HTTP 200 with standard Prometheus text exposition content."""
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    assert "# HELP sentinelscale_observations_total" in res.text
    assert "# TYPE sentinelscale_observations_total counter"

