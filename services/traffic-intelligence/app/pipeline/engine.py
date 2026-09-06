import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional
from app.config.settings import settings
from app.models.traffic import (
    AssessmentRequest,
    StatusCodeDistribution,
    TrafficAssessment,
    TrafficClassification,
    TrafficTelemetryInput,
)
from app.pipeline.burst_detector import BurstDetector
from app.pipeline.classifier import TrafficClassifier
from app.pipeline.features import FeatureExtractor
from app.pipeline.ml_detector import IsolationForestAnomalyDetector
from app.pipeline.scorer import ScoreResult, TrafficScorer


class TrafficIntelligenceEngine:
    """
    Hybrid Intelligence Pipeline Orchestrator.
    Combines deterministic heuristic rules with unsupervised ML (Isolation Forest)
    anomaly detection to evaluate AssessmentRequests into schema-conforming TrafficAssessments.
    """

    def __init__(self):
        self.feature_extractor = FeatureExtractor()
        self.burst_detector = BurstDetector()
        self.scorer = TrafficScorer()
        self.classifier = TrafficClassifier()
        self.ml_detector = IsolationForestAnomalyDetector()

    def evaluate(self, request: AssessmentRequest) -> TrafficAssessment:
        trace_id = request.trace_id or f"trace-{uuid.uuid4().hex[:16]}"
        event_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        # If telemetry is explicitly provided in the request, evaluate it
        if request.telemetry is not None:
            telemetry = request.telemetry
        else:
            # If telemetry is omitted, evaluate representative default telemetry
            telemetry = TrafficTelemetryInput(
                total_requests=int(2500.0 * request.window_seconds),
                total_rps=2500.0,
                baseline_rps=1000.0,
                status_codes=StatusCodeDistribution(
                    status_2xx=int(1250 * request.window_seconds),
                    status_3xx=int(250 * request.window_seconds),
                    status_4xx=int(800 * request.window_seconds),
                    status_5xx=int(200 * request.window_seconds),
                ),
                top_ip_ratio=0.55,
                unique_ip_count=120,
                non_standard_ua_ratio=0.45,
                single_endpoint_ratio=0.70,
            )

        features = self.feature_extractor.extract(
            telemetry,
            window_seconds=request.window_seconds
        )
        burst = self.burst_detector.detect(features)
        heuristic_scores = self.scorer.calculate_scores(
            features,
            burst,
            window_seconds=request.window_seconds
        )

        # Evaluate ML Anomaly Detector if enabled and available
        ml_result = None
        if settings.ENABLE_ML_ANOMALY_DETECTOR and features.has_telemetry:
            ml_result = self.ml_detector.detect(asdict(features))

        # Hybrid Scoring Synthesis
        if ml_result and ml_result.is_available:
            w_ml = settings.ML_ANOMALY_WEIGHT
            # Weighted synthesis of heuristic risk and ML anomaly score
            # Protect legitimate flash crowds: if heuristic risk is very low (< 0.20), don't falsely elevate
            if heuristic_scores.risk_score < 0.20 and features.ip_concentration < 0.15 and features.ua_anomaly_ratio < 0.05:
                hybrid_risk = heuristic_scores.risk_score
            else:
                hybrid_risk = round(
                    ((1.0 - w_ml) * heuristic_scores.risk_score) + (w_ml * ml_result.anomaly_score),
                    2
                )
                hybrid_risk = max(0.0, min(1.0, hybrid_risk))

            # Legitimacy score adjusts with hybrid risk
            hybrid_legitimacy = round(
                max(0.0, min(1.0, (1.0 - hybrid_risk) * 0.50 + (heuristic_scores.legitimacy_score * 0.50))),
                2
            )

            # Re-partition RPS based on hybrid risk
            total_rps = features.total_rps
            if total_rps <= 0.0:
                legitimate_rps = 0.0
                suspicious_rps = 0.0
            else:
                if hybrid_risk < 0.20:
                    suspicious_fraction = 0.0
                else:
                    suspicious_fraction = max(
                        hybrid_risk,
                        (features.ip_concentration * 0.6 + features.ua_anomaly_ratio * 0.4)
                    )
                    suspicious_fraction = max(0.0, min(1.0, suspicious_fraction))

                suspicious_rps = round(total_rps * suspicious_fraction, 2)
                legitimate_rps = round(total_rps - suspicious_rps, 2)

            final_scores = ScoreResult(
                risk_score=hybrid_risk,
                legitimacy_score=hybrid_legitimacy,
                confidence=heuristic_scores.confidence,
                legitimate_rps_estimate=legitimate_rps,
                suspicious_rps_estimate=suspicious_rps,
            )
            ml_signal = ml_result.signal_tag if ml_result.is_anomaly else None
        else:
            final_scores = heuristic_scores
            ml_signal = None

        classification_result = self.classifier.classify(features, burst, final_scores, ml_signal=ml_signal)

        return TrafficAssessment(
            event_id=event_id,
            trace_id=trace_id,
            timestamp=timestamp,
            contract_version=settings.CONTRACT_VERSION,
            service_version=settings.SERVICE_VERSION,
            model_version=settings.MODEL_VERSION,
            window_seconds=request.window_seconds,
            total_rps=features.total_rps,
            legitimate_rps_estimate=final_scores.legitimate_rps_estimate,
            suspicious_rps_estimate=final_scores.suspicious_rps_estimate,
            risk_score=final_scores.risk_score,
            legitimacy_score=final_scores.legitimacy_score,
            confidence=final_scores.confidence,
            classification=classification_result.classification,
            top_signals=classification_result.top_signals,
        )
