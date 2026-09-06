from dataclasses import dataclass
from typing import List
from app.config.settings import settings
from app.models.traffic import TrafficClassification
from app.pipeline.burst_detector import BurstDetectionResult
from app.pipeline.features import ExtractedTrafficFeatures
from app.pipeline.scorer import ScoreResult


@dataclass(frozen=True)
class ClassificationResult:
    classification: TrafficClassification
    top_signals: List[str]


class TrafficClassifier:
    """Categorizes traffic and generates explainability signals."""

    @staticmethod
    def classify(
        features: ExtractedTrafficFeatures,
        burst_result: BurstDetectionResult,
        scores: ScoreResult,
        ml_signal: str | None = None,
    ) -> ClassificationResult:
        if not features.has_telemetry:
            return ClassificationResult(
                classification=TrafficClassification.UNKNOWN,
                top_signals=["insufficient_telemetry", "unknown_traffic_profile"]
            )

        signals: List[str] = []

        # 0. ML Anomaly signal if present
        if ml_signal:
            signals.append(ml_signal)

        # 1. Burst signal
        if burst_result.signal_tag:
            signals.append(burst_result.signal_tag)

        # 2. IP Concentration signal
        if features.ip_concentration >= settings.IP_CONCENTRATION_CRITICAL:
            signals.append("critical_ip_concentration")
        elif features.ip_concentration >= settings.IP_CONCENTRATION_HIGH:
            signals.append("client_ip_concentration")

        # 3. User-Agent signal
        if features.ua_anomaly_ratio >= settings.UA_ANOMALY_CRITICAL:
            signals.append("critical_bot_ua_signature")
        elif features.ua_anomaly_ratio >= settings.UA_ANOMALY_HIGH:
            signals.append("non_standard_user_agent")

        # 4. Error rate signal
        if features.error_rate >= settings.ERROR_RATE_HIGH:
            signals.append("high_error_rate")
        elif features.error_rate >= settings.ERROR_RATE_ELEVATED:
            signals.append("elevated_error_rate")

        # 5. Endpoint concentration signal
        if features.single_endpoint_ratio >= 0.85:
            signals.append("single_endpoint_flood")

        # 6. Legitimate profile signals
        if (
            scores.risk_score < settings.RISK_THRESHOLD_SUSPICIOUS and
            features.ip_concentration < settings.IP_CONCENTRATION_HIGH and
            features.ua_anomaly_ratio < settings.UA_ANOMALY_HIGH
        ):
            signals.append("legitimate_traffic_profile")
            if burst_result.is_burst:
                signals.append("organic_demand_surge")

        # Fallback signal if list is empty
        if not signals:
            signals.append("nominal_traffic_profile")

        # Determine Classification
        if scores.risk_score >= settings.RISK_THRESHOLD_MALICIOUS:
            classification = TrafficClassification.MALICIOUS
        elif scores.risk_score >= settings.RISK_THRESHOLD_SUSPICIOUS:
            classification = TrafficClassification.SUSPICIOUS
        else:
            classification = TrafficClassification.LEGITIMATE

        # Return top signals (limit to 5)
        return ClassificationResult(
            classification=classification,
            top_signals=signals[:5]
        )

