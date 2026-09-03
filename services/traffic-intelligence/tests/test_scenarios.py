import json
from pathlib import Path
import jsonschema
import pytest
from app.models.traffic import (
    AssessmentRequest,
    StatusCodeDistribution,
    TrafficClassification,
    TrafficTelemetryInput,
)
from app.pipeline.engine import TrafficIntelligenceEngine


@pytest.fixture
def json_schema():
    schema_path = Path(__file__).resolve().parents[3] / "contracts" / "traffic" / "traffic_assessment.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def engine():
    return TrafficIntelligenceEngine()


def test_scenario_1_normal_legitimate_traffic(engine, json_schema):
    """
    Scenario 1: Normal steady-state traffic with organic user distribution,
    low error rates, standard browsers/devices.
    """
    req = AssessmentRequest(
        window_seconds=60,
        telemetry=TrafficTelemetryInput(
            total_requests=3000,
            total_rps=50.0,
            baseline_rps=50.0,
            status_codes=StatusCodeDistribution(
                status_2xx=2940,
                status_3xx=30,
                status_4xx=25,
                status_5xx=5,
            ),
            top_ip_ratio=0.03,
            unique_ip_count=800,
            non_standard_ua_ratio=0.01,
            single_endpoint_ratio=0.25,
        ),
    )
    result = engine.evaluate(req)

    assert result.classification == TrafficClassification.LEGITIMATE
    assert result.risk_score < 0.30
    assert result.legitimacy_score >= 0.70
    assert result.legitimate_rps_estimate == result.total_rps
    assert result.suspicious_rps_estimate == 0.0
    assert "legitimate_traffic_profile" in result.top_signals

    # Schema Conformance
    jsonschema.validate(instance=result.model_dump(), schema=json_schema)


def test_scenario_2_sudden_legitimate_spike(engine, json_schema):
    """
    Scenario 2: Sudden organic surge (flash crowd / promo launch).
    High burst ratio, but legitimate IP distribution and normal status codes.
    """
    req = AssessmentRequest(
        window_seconds=60,
        telemetry=TrafficTelemetryInput(
            total_requests=18000,
            total_rps=300.0,
            baseline_rps=100.0,  # 3x spike
            status_codes=StatusCodeDistribution(
                status_2xx=17500,
                status_3xx=200,
                status_4xx=280,
                status_5xx=20,
            ),
            top_ip_ratio=0.05,  # Natural distribution across many clients
            unique_ip_count=4500,
            non_standard_ua_ratio=0.02,
            single_endpoint_ratio=0.40,
        ),
    )
    result = engine.evaluate(req)

    assert result.classification == TrafficClassification.LEGITIMATE
    assert result.risk_score < 0.40
    assert result.legitimacy_score >= 0.60
    assert result.legitimate_rps_estimate > result.suspicious_rps_estimate
    assert "high_burst_rate" in result.top_signals
    assert "organic_demand_surge" in result.top_signals

    # Schema Conformance
    jsonschema.validate(instance=result.model_dump(), schema=json_schema)


def test_scenario_3_suspicious_burst_traffic(engine, json_schema):
    """
    Scenario 3: Suspicious burst traffic with elevated error rates and moderate IP concentration.
    """
    req = AssessmentRequest(
        window_seconds=60,
        telemetry=TrafficTelemetryInput(
            total_requests=30000,
            total_rps=500.0,
            baseline_rps=100.0,  # 5x burst
            status_codes=StatusCodeDistribution(
                status_2xx=18000,
                status_3xx=1000,
                status_4xx=9000,
                status_5xx=2000,
            ),
            top_ip_ratio=0.45,  # Elevated IP concentration
            unique_ip_count=300,
            non_standard_ua_ratio=0.40,  # Elevated bot UA ratio
            single_endpoint_ratio=0.75,
        ),
    )
    result = engine.evaluate(req)

    assert result.classification in [TrafficClassification.SUSPICIOUS, TrafficClassification.MALICIOUS]
    assert result.risk_score >= 0.50
    assert result.suspicious_rps_estimate > 0.0
    assert "extreme_burst_rate" in result.top_signals

    # Schema Conformance
    jsonschema.validate(instance=result.model_dump(), schema=json_schema)


def test_scenario_4_highly_concentrated_suspicious_traffic(engine, json_schema):
    """
    Scenario 4: Highly concentrated hostile traffic (credential stuffing / L7 flood).
    Extreme IP concentration, scrapers/bots, high 4xx/5xx failure rates.
    """
    req = AssessmentRequest(
        window_seconds=60,
        telemetry=TrafficTelemetryInput(
            total_requests=60000,
            total_rps=1000.0,
            baseline_rps=100.0,  # 10x flood
            status_codes=StatusCodeDistribution(
                status_2xx=5000,
                status_3xx=0,
                status_4xx=50000,  # 83% error rate
                status_5xx=5000,
            ),
            top_ip_ratio=0.85,  # 85% traffic from 1 IP or subnet
            unique_ip_count=12,
            non_standard_ua_ratio=0.90,  # 90% curl/python-requests/empty UA
            single_endpoint_ratio=0.95,
        ),
    )
    result = engine.evaluate(req)

    assert result.classification == TrafficClassification.MALICIOUS
    assert result.risk_score >= 0.80
    assert result.legitimacy_score <= 0.30
    assert result.suspicious_rps_estimate > (0.8 * result.total_rps)
    assert "critical_ip_concentration" in result.top_signals
    assert "critical_bot_ua_signature" in result.top_signals

    # Schema Conformance
    jsonschema.validate(instance=result.model_dump(), schema=json_schema)


def test_scenario_5_mixed_legitimate_and_suspicious_traffic(engine, json_schema):
    """
    Scenario 5: Mixed traffic. Legitimate baseline plus a background scraper swarm.
    """
    req = AssessmentRequest(
        window_seconds=60,
        telemetry=TrafficTelemetryInput(
            total_requests=12000,
            total_rps=200.0,
            baseline_rps=100.0,  # 2x rate
            status_codes=StatusCodeDistribution(
                status_2xx=7500,
                status_3xx=500,
                status_4xx=3500,
                status_5xx=500,
            ),
            top_ip_ratio=0.42,
            unique_ip_count=250,
            non_standard_ua_ratio=0.38,
            single_endpoint_ratio=0.60,
        ),
    )
    result = engine.evaluate(req)

    assert result.classification == TrafficClassification.SUSPICIOUS
    assert 0.40 <= result.risk_score <= 0.80
    assert result.legitimate_rps_estimate > 0.0
    assert result.suspicious_rps_estimate > 0.0
    assert round(result.legitimate_rps_estimate + result.suspicious_rps_estimate, 2) == result.total_rps

    # Schema Conformance
    jsonschema.validate(instance=result.model_dump(), schema=json_schema)


def test_scenario_6_insufficient_or_unknown_evidence(engine, json_schema):
    """
    Scenario 6: Telemetry absent or evaluation window empty.
    Service emits graceful 'unknown' classification with explainability signals.
    """
    req = AssessmentRequest(
        window_seconds=10,
        telemetry=None,
    )
    # When explicit features are extracted without telemetry
    from app.pipeline.features import FeatureExtractor
    from app.pipeline.burst_detector import BurstDetector
    from app.pipeline.scorer import TrafficScorer
    from app.pipeline.classifier import TrafficClassifier

    features = FeatureExtractor.extract(None, window_seconds=10)
    burst = BurstDetector.detect(features)
    scores = TrafficScorer.calculate_scores(features, burst, window_seconds=10)
    classification_res = TrafficClassifier.classify(features, burst, scores)

    assert classification_res.classification == TrafficClassification.UNKNOWN
    assert "insufficient_telemetry" in classification_res.top_signals
    assert scores.confidence <= 0.40

