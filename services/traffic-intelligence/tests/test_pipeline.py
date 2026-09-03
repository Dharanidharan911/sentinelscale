import pytest
from app.config.settings import settings
from app.models.traffic import (
    AssessmentRequest,
    StatusCodeDistribution,
    TrafficClassification,
    TrafficTelemetryInput,
)
from app.pipeline.burst_detector import BurstDetector, BurstLevel
from app.pipeline.classifier import TrafficClassifier
from app.pipeline.engine import TrafficIntelligenceEngine
from app.pipeline.features import FeatureExtractor
from app.pipeline.scorer import TrafficScorer


def test_feature_extractor_none():
    features = FeatureExtractor.extract(None)
    assert not features.has_telemetry
    assert features.total_rps == 0.0
    assert features.burst_ratio == 1.0
    assert features.data_completeness == 0.0


def test_feature_extractor_valid():
    telemetry = TrafficTelemetryInput(
        total_requests=6000,
        total_rps=100.0,
        baseline_rps=50.0,
        status_codes=StatusCodeDistribution(
            status_2xx=5700,
            status_3xx=100,
            status_4xx=150,
            status_5xx=50,
        ),
        top_ip_ratio=0.10,
        unique_ip_count=500,
        non_standard_ua_ratio=0.02,
        single_endpoint_ratio=0.30,
    )
    features = FeatureExtractor.extract(telemetry)
    assert features.has_telemetry
    assert features.total_rps == 100.0
    assert features.burst_ratio == 2.0
    assert features.error_rate == pytest.approx((150 + 50) / 6000, abs=1e-4)
    assert features.ip_concentration == 0.10
    assert features.ua_anomaly_ratio == 0.02
    assert features.data_completeness == 1.0


def test_burst_detector_levels():
    def make_features(ratio: float):
        from app.pipeline.features import ExtractedTrafficFeatures
        return ExtractedTrafficFeatures(
            total_rps=100.0,
            burst_ratio=ratio,
            error_rate=0.01,
            ip_concentration=0.05,
            ua_anomaly_ratio=0.01,
            single_endpoint_ratio=0.2,
            has_telemetry=True,
            data_completeness=1.0,
        )

    # Nominal (< 1.75)
    res_nominal = BurstDetector.detect(make_features(1.2))
    assert res_nominal.level == BurstLevel.NOMINAL
    assert not res_nominal.is_burst

    # Elevated (>= 1.75, < 2.5)
    res_elevated = BurstDetector.detect(make_features(2.0))
    assert res_elevated.level == BurstLevel.ELEVATED
    assert res_elevated.is_burst
    assert res_elevated.signal_tag == "elevated_traffic_burst"

    # Spike (>= 2.5, < 4.0)
    res_spike = BurstDetector.detect(make_features(3.0))
    assert res_spike.level == BurstLevel.SPIKE
    assert res_spike.is_burst
    assert res_spike.signal_tag == "high_burst_rate"

    # Extreme (>= 4.0)
    res_extreme = BurstDetector.detect(make_features(5.0))
    assert res_extreme.level == BurstLevel.EXTREME
    assert res_extreme.is_burst
    assert res_extreme.signal_tag == "extreme_burst_rate"


def test_scorer_clean_partition():
    engine = TrafficIntelligenceEngine()
    req = AssessmentRequest(
        window_seconds=60,
        telemetry=TrafficTelemetryInput(
            total_requests=6000,
            total_rps=100.0,
            baseline_rps=100.0,
            status_codes=StatusCodeDistribution(status_2xx=6000),
            top_ip_ratio=0.05,
            unique_ip_count=1000,
            non_standard_ua_ratio=0.01,
            single_endpoint_ratio=0.2,
        ),
    )
    assessment = engine.evaluate(req)
    assert round(assessment.legitimate_rps_estimate + assessment.suspicious_rps_estimate, 2) == assessment.total_rps
    assert assessment.classification == TrafficClassification.LEGITIMATE
    assert assessment.risk_score <= 0.20
    assert assessment.legitimacy_score >= 0.70
