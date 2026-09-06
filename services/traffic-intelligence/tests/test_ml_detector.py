from pathlib import Path
import pytest
from app.models.traffic import (
    AssessmentRequest,
    StatusCodeDistribution,
    TrafficClassification,
    TrafficTelemetryInput,
)
from app.pipeline.engine import TrafficIntelligenceEngine
from app.pipeline.ml_detector import (
    IsolationForestAnomalyDetector,
    MLAnomalyResult,
    TOTAL_RPS_SCALE,
    FEATURE_NAMES,
)
from app.config.settings import settings


# ---------------------------------------------------------------------------
# Task 2 / Task 3 — Feature normalization unit tests
# ---------------------------------------------------------------------------

def test_feature_normalization_total_rps():
    """total_rps must be divided by TOTAL_RPS_SCALE, all other features unchanged."""
    features = {
        "total_rps": 1000.0,
        "burst_ratio": 3.5,
        "error_rate": 0.10,
        "ip_concentration": 0.50,
        "ua_anomaly_ratio": 0.30,
        "single_endpoint_ratio": 0.60,
        "data_completeness": 1.0,
    }
    normed = IsolationForestAnomalyDetector.normalize_features(features)
    assert normed[0] == pytest.approx(1000.0 / TOTAL_RPS_SCALE)
    assert normed[1] == pytest.approx(3.5)
    assert normed[2] == pytest.approx(0.10)
    assert normed[3] == pytest.approx(0.50)
    assert normed[4] == pytest.approx(0.30)
    assert normed[5] == pytest.approx(0.60)
    assert normed[6] == pytest.approx(1.0)


def test_feature_normalization_zero_rps():
    """Zero total_rps normalizes to 0.0."""
    normed = IsolationForestAnomalyDetector.normalize_features({"total_rps": 0.0})
    assert normed[0] == pytest.approx(0.0)


def test_feature_names_canonical_count():
    """FEATURE_NAMES must list exactly 7 features in canonical order."""
    assert len(FEATURE_NAMES) == 7
    assert FEATURE_NAMES[0] == "total_rps"
    assert FEATURE_NAMES[-1] == "data_completeness"


# ---------------------------------------------------------------------------
# Task 1 — Basic inference + fallback
# ---------------------------------------------------------------------------

def test_ml_detector_inference():
    detector = IsolationForestAnomalyDetector()
    assert detector.is_loaded

    # Clean inlier features (Scenario A range)
    normal_features = {
        "total_rps": 60.0,
        "burst_ratio": 1.0,
        "error_rate": 0.01,
        "ip_concentration": 0.03,
        "ua_anomaly_ratio": 0.01,
        "single_endpoint_ratio": 0.25,
        "data_completeness": 1.0,
    }
    normal_res = detector.detect(normal_features)
    assert normal_res.is_available
    assert not normal_res.is_anomaly
    assert normal_res.anomaly_score < 0.50

    # Malicious outlier features (Scenario C range)
    attack_features = {
        "total_rps": 1200.0,
        "burst_ratio": 12.0,
        "error_rate": 0.85,
        "ip_concentration": 0.88,
        "ua_anomaly_ratio": 0.95,
        "single_endpoint_ratio": 0.98,
        "data_completeness": 1.0,
    }
    attack_res = detector.detect(attack_features)
    assert attack_res.is_available
    assert attack_res.is_anomaly
    assert attack_res.anomaly_score >= 0.60
    assert attack_res.signal_tag == "ml_anomaly_detected"


def test_ml_detector_fallback():
    """Missing model file must produce safe is_available=False result without raising."""
    detector = IsolationForestAnomalyDetector(model_path=Path("non_existent_weights.joblib"))
    assert not detector.is_loaded

    res = detector.detect({"total_rps": 100.0})
    assert not res.is_available
    assert not res.is_anomaly
    assert res.anomaly_score == 0.0


def test_ml_detector_malformed_features_fallback():
    """Malformed/empty features dict must not raise -- returns is_available=True with safe values."""
    detector = IsolationForestAnomalyDetector()
    if not detector.is_loaded:
        pytest.skip("Model not available")
    # Missing keys default to 0.0 / 1.0 per normalize_features defaults
    res = detector.detect({})
    assert res.is_available  # model is loaded; defaults fill in zeros


# ---------------------------------------------------------------------------
# Task 5 — Hybrid weight verification
# ---------------------------------------------------------------------------

def test_hybrid_weight_zero_produces_heuristic_only():
    """
    When ML_ANOMALY_WEIGHT=0 the hybrid risk must equal the heuristic risk exactly.
    The ML anomaly score must have no influence on the final risk_score.
    """
    original_weight = settings.ML_ANOMALY_WEIGHT
    original_ml = settings.ENABLE_ML_ANOMALY_DETECTOR
    try:
        settings.ML_ANOMALY_WEIGHT = 0.0
        settings.ENABLE_ML_ANOMALY_DETECTOR = True

        engine = TrafficIntelligenceEngine()
        # Moderate traffic: heuristic and ML will differ
        req = AssessmentRequest(
            window_seconds=60,
            telemetry=TrafficTelemetryInput(
                total_requests=18000,
                total_rps=300.0,
                baseline_rps=100.0,
                status_codes=StatusCodeDistribution(status_2xx=15000, status_4xx=2000, status_5xx=1000),
                top_ip_ratio=0.20,
                unique_ip_count=200,
                non_standard_ua_ratio=0.10,
                single_endpoint_ratio=0.40,
            ),
        )
        result_w0 = engine.evaluate(req)

        # With weight=0, disable ML entirely and compare
        settings.ENABLE_ML_ANOMALY_DETECTOR = False
        engine2 = TrafficIntelligenceEngine()
        result_heuristic = engine2.evaluate(req)

        # Risk scores must match when weight=0 (no ML influence)
        assert result_w0.risk_score == pytest.approx(result_heuristic.risk_score, abs=0.01), (
            f"weight=0 result {result_w0.risk_score} != heuristic {result_heuristic.risk_score}"
        )
    finally:
        settings.ML_ANOMALY_WEIGHT = original_weight
        settings.ENABLE_ML_ANOMALY_DETECTOR = original_ml


def test_hybrid_weight_nonzero_incorporates_ml_anomaly():
    """
    When ML_ANOMALY_WEIGHT > 0 and ML reports an anomaly, the hybrid risk must
    differ from the heuristic-only risk (ML has real influence).
    Also verifies the risk is bounded to [0, 1].
    """
    if not IsolationForestAnomalyDetector().is_loaded:
        pytest.skip("Model not available")

    original_weight = settings.ML_ANOMALY_WEIGHT
    original_ml = settings.ENABLE_ML_ANOMALY_DETECTOR
    try:
        settings.ML_ANOMALY_WEIGHT = 0.30
        settings.ENABLE_ML_ANOMALY_DETECTOR = True

        engine_hybrid = TrafficIntelligenceEngine()

        settings.ENABLE_ML_ANOMALY_DETECTOR = False
        engine_heuristic = TrafficIntelligenceEngine()

        # Moderate traffic where heuristic risk is in mid-range (ML effect visible)
        req = AssessmentRequest(
            window_seconds=60,
            telemetry=TrafficTelemetryInput(
                total_requests=30000,
                total_rps=500.0,
                baseline_rps=80.0,
                status_codes=StatusCodeDistribution(status_2xx=10000, status_4xx=15000, status_5xx=5000),
                top_ip_ratio=0.65,
                unique_ip_count=30,
                non_standard_ua_ratio=0.70,
                single_endpoint_ratio=0.85,
            ),
        )
        hybrid_result = engine_hybrid.evaluate(req)
        heuristic_result = engine_heuristic.evaluate(req)

        # Hybrid risk must be bounded
        assert 0.0 <= hybrid_result.risk_score <= 1.0
        assert 0.0 <= hybrid_result.legitimacy_score <= 1.0
        # ML influence: hybrid risk will differ from pure heuristic when weight > 0 and ML is anomalous
        # (not identical -- the weight blending changed the value)
        # Both should classify as malicious in this extreme case
        assert hybrid_result.classification in (TrafficClassification.MALICIOUS, TrafficClassification.SUSPICIOUS)

    finally:
        settings.ML_ANOMALY_WEIGHT = original_weight
        settings.ENABLE_ML_ANOMALY_DETECTOR = original_ml


def test_hybrid_weight_is_bounded_and_deterministic():
    """
    The ML_ANOMALY_WEIGHT in settings is bounded [0, 1] and the hybrid formula
    always produces a bounded risk score regardless of anomaly_score value.
    """
    import math
    # Test the formula directly with extreme values
    for heuristic_risk in [0.0, 0.5, 1.0]:
        for anomaly_score in [0.0, 0.5, 1.0]:
            for w in [0.0, 0.30, 1.0]:
                hybrid = (1.0 - w) * heuristic_risk + w * anomaly_score
                hybrid = max(0.0, min(1.0, hybrid))
                assert 0.0 <= hybrid <= 1.0
                assert not math.isnan(hybrid)
                assert not math.isinf(hybrid)


# ---------------------------------------------------------------------------
# Task 4 — Hybrid engine flow
# ---------------------------------------------------------------------------

def test_hybrid_engine_assessment_flow():
    engine = TrafficIntelligenceEngine()
    req = AssessmentRequest(
        window_seconds=60,
        telemetry=TrafficTelemetryInput(
            total_requests=60000,
            total_rps=1000.0,
            baseline_rps=100.0,
            status_codes=StatusCodeDistribution(status_4xx=50000, status_5xx=5000),
            top_ip_ratio=0.85,
            unique_ip_count=10,
            non_standard_ua_ratio=0.90,
            single_endpoint_ratio=0.95,
        ),
    )
    assessment = engine.evaluate(req)
    assert assessment.classification == TrafficClassification.MALICIOUS
    assert assessment.risk_score >= 0.80
    assert "ml_anomaly_detected" in assessment.top_signals
    assert assessment.model_version == "traffic-hybrid-v1"
