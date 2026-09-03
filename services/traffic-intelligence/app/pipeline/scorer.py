from dataclasses import dataclass
from app.config.settings import settings
from app.pipeline.burst_detector import BurstDetectionResult, BurstLevel
from app.pipeline.features import ExtractedTrafficFeatures


@dataclass(frozen=True)
class ScoreResult:
    risk_score: float
    legitimacy_score: float
    confidence: float
    legitimate_rps_estimate: float
    suspicious_rps_estimate: float


class TrafficScorer:
    """
    Computes risk score, legitimacy score, confidence, and partitions
    traffic into estimated legitimate vs suspicious RPS.
    """

    @staticmethod
    def calculate_scores(
        features: ExtractedTrafficFeatures,
        burst_result: BurstDetectionResult,
        window_seconds: int
    ) -> ScoreResult:
        if not features.has_telemetry:
            # When no telemetry is supplied, return neutral unknown state
            return ScoreResult(
                risk_score=0.10,
                legitimacy_score=0.50,
                confidence=0.30,
                legitimate_rps_estimate=0.0,
                suspicious_rps_estimate=0.0,
            )

        # 1. Calculate Component Risk Penalties
        # IP concentration risk (weight: 0.35)
        ip_risk = min(1.0, features.ip_concentration / settings.IP_CONCENTRATION_CRITICAL)

        # UA anomaly risk (weight: 0.30)
        ua_risk = min(1.0, features.ua_anomaly_ratio / settings.UA_ANOMALY_CRITICAL)

        # Error rate risk (weight: 0.20)
        error_risk = min(1.0, features.error_rate / settings.ERROR_RATE_HIGH)

        # Burst risk (weight: 0.15)
        if burst_result.level == BurstLevel.EXTREME:
            burst_risk = 1.0
        elif burst_result.level == BurstLevel.SPIKE:
            burst_risk = 0.70
        elif burst_result.level == BurstLevel.ELEVATED:
            burst_risk = 0.35
        else:
            burst_risk = 0.0

        # Weighted Risk Score
        # If IP concentration and UA anomaly are both very low, even a spike can be legitimate
        raw_risk = (
            (ip_risk * 0.35) +
            (ua_risk * 0.30) +
            (error_risk * 0.20) +
            (burst_risk * 0.15)
        )

        # If malicious indicators (IP concentration >= critical and UA anomaly >= critical), elevate risk
        if (
            features.ip_concentration >= settings.IP_CONCENTRATION_CRITICAL and
            features.ua_anomaly_ratio >= settings.UA_ANOMALY_HIGH
        ):
            raw_risk = max(raw_risk, 0.85)

        # If clean legitimate indicators (low IP concentration, clean UA, low errors), clamp risk down
        if (
            features.ip_concentration <= 0.15 and
            features.ua_anomaly_ratio <= 0.05 and
            features.error_rate <= 0.05
        ):
            raw_risk = min(raw_risk, 0.20)

        risk_score = round(max(0.0, min(1.0, raw_risk)), 2)

        # 2. Calculate Legitimacy Score
        # Legitimacy is inversely related to malicious indicators, scaled by natural dispersion
        natural_spread_factor = max(0.0, 1.0 - features.ip_concentration)
        legitimate_ua_factor = max(0.0, 1.0 - features.ua_anomaly_ratio)
        low_error_factor = max(0.0, 1.0 - (features.error_rate * 2.0))

        raw_legitimacy = (
            (1.0 - risk_score) * 0.50 +
            (natural_spread_factor * 0.20) +
            (legitimate_ua_factor * 0.20) +
            (low_error_factor * 0.10)
        )
        legitimacy_score = round(max(0.0, min(1.0, raw_legitimacy)), 2)

        # 3. Calculate Confidence
        # Duration factor: window >= 60s gives max time confidence
        duration_factor = min(1.0, window_seconds / float(settings.IDEAL_WINDOW_SECONDS_CONFIDENCE))
        raw_confidence = (0.50 * duration_factor) + (0.50 * features.data_completeness)
        confidence = round(max(0.10, min(1.0, raw_confidence)), 2)

        # 4. Partition Total RPS into Legitimate and Suspicious
        total_rps = features.total_rps
        if total_rps <= 0.0:
            legitimate_rps = 0.0
            suspicious_rps = 0.0
        else:
            # Estimate suspicious volume directly from risk factor applied to total rate
            # In severe concentrated attacks, suspicious proportion is directly driven by IP/UA anomaly
            suspicious_fraction = max(risk_score, (features.ip_concentration * 0.6 + features.ua_anomaly_ratio * 0.4))
            # Bound suspicious fraction between 0.0 and 1.0
            suspicious_fraction = max(0.0, min(1.0, suspicious_fraction))

            # If risk is very low (< 0.20), treat almost all traffic as legitimate
            if risk_score < 0.20:
                suspicious_fraction = 0.0

            suspicious_rps = round(total_rps * suspicious_fraction, 2)
            legitimate_rps = round(total_rps - suspicious_rps, 2)

        return ScoreResult(
            risk_score=risk_score,
            legitimacy_score=legitimacy_score,
            confidence=confidence,
            legitimate_rps_estimate=legitimate_rps,
            suspicious_rps_estimate=suspicious_rps,
        )

