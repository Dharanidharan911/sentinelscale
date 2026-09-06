from pathlib import Path
import pytest
from app.models.traffic import (
    AssessmentRequest,
    StatusCodeDistribution,
    TrafficClassification,
    TrafficTelemetryInput,
)
from app.pipeline.engine import TrafficIntelligenceEngine
from app.pipeline.ml_detector import IsolationForestAnomalyDetector, MLAnomalyResult


def test_ml_detector_inference():
    detector = IsolationForestAnomalyDetector()
    assert detector.is_loaded

    # Clean inlier features
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

    # Malicious outlier features
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
    # Provide non-existent model path to test safe fallback
    detector = IsolationForestAnomalyDetector(model_path=Path("non_existent_weights.joblib"))
    assert not detector.is_loaded

    res = detector.detect({"total_rps": 100.0})
    assert not res.is_available
    assert not res.is_anomaly
    assert res.anomaly_score == 0.0


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
