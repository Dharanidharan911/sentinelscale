from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.models.anomaly import (
    AnomalyAssessment,
    AnomalySeverity,
    AnomalySignal,
    MetricBaseline,
    SignalDirection,
)
from app.models.history import StoredObservation
from app.services.history.base import DecisionHistoryStore
from app.services.intelligence.baseline import BehavioralBaselineService
from app.services.intelligence.historical import parse_and_validate_time_window

NORMAL_Z_THRESHOLD: float = 1.5
ELEVATED_Z_THRESHOLD: float = 2.5
MINIMUM_BASELINE_SAMPLES: int = 5


class AnomalyIntelligenceService:
    """
    Deterministic Behavioral Anomaly Intelligence Service.
    Compares current observation metrics against historical reference baselines
    to detect abnormal demand, security risk surges, capacity degradation, or HPA divergence.
    """

    def __init__(
        self,
        history_store: DecisionHistoryStore,
        baseline_service: Optional[BehavioralBaselineService] = None,
        min_samples: int = MINIMUM_BASELINE_SAMPLES,
    ):
        self._history_store = history_store
        self._baseline_service = baseline_service or BehavioralBaselineService()
        self.min_samples = min_samples

    def _score_signal(
        self,
        metric_name: str,
        current_value: float,
        baseline: MetricBaseline,
    ) -> AnomalySignal:
        mean = baseline.mean
        stddev = baseline.stddev
        deviation = round(current_value - mean, 4)

        # 1. Determine Direction
        if abs(deviation) <= 1e-5:
            direction = SignalDirection.NEAR_BASELINE
        elif deviation > 0:
            direction = SignalDirection.HIGHER_THAN_BASELINE
        else:
            direction = SignalDirection.LOWER_THAN_BASELINE

        # 2. Cold start / Insufficient Samples
        if baseline.sample_count < self.min_samples:
            return AnomalySignal(
                metric=metric_name,
                current_value=current_value,
                baseline_mean=mean,
                baseline_stddev=stddev,
                deviation=deviation,
                z_score=None,
                severity=AnomalySeverity.INSUFFICIENT_DATA,
                direction=direction,
                sample_count=baseline.sample_count,
                interpretation=f"Insufficient baseline history ({baseline.sample_count}/{self.min_samples} samples).",
            )

        # 3. Calculate Z-Score & Severity
        if stddev > 1e-6:
            z_score = round(deviation / stddev, 3)
            abs_z = abs(z_score)
            if abs_z >= ELEVATED_Z_THRESHOLD:
                severity = AnomalySeverity.ANOMALOUS
            elif abs_z >= NORMAL_Z_THRESHOLD:
                severity = AnomalySeverity.ELEVATED
            else:
                severity = AnomalySeverity.NORMAL
        else:
            # Zero-variance deterministic fallback
            if direction == SignalDirection.NEAR_BASELINE:
                z_score = 0.0
                severity = AnomalySeverity.NORMAL
            else:
                sign = 1.0 if deviation > 0 else -1.0
                if abs(mean) > 1e-6:
                    rel_diff = abs(deviation) / abs(mean)
                    if rel_diff >= 0.50:
                        z_score = sign * 3.0
                        severity = AnomalySeverity.ANOMALOUS
                    elif rel_diff >= 0.20:
                        z_score = sign * 2.0
                        severity = AnomalySeverity.ELEVATED
                    else:
                        z_score = sign * 1.0
                        severity = AnomalySeverity.NORMAL
                else:
                    z_score = sign * 3.0
                    severity = AnomalySeverity.ANOMALOUS

        # 4. Generate Domain-Aware Interpretation
        interpretation = self._generate_signal_interpretation(metric_name, severity, direction, current_value, mean)

        return AnomalySignal(
            metric=metric_name,
            current_value=current_value,
            baseline_mean=mean,
            baseline_stddev=stddev,
            deviation=deviation,
            z_score=z_score,
            severity=severity,
            direction=direction,
            sample_count=baseline.sample_count,
            interpretation=interpretation,
        )

    def _generate_signal_interpretation(
        self,
        metric: str,
        severity: AnomalySeverity,
        direction: SignalDirection,
        current: float,
        mean: float,
    ) -> str:
        if severity == AnomalySeverity.NORMAL:
            return f"{metric} is operating within normal baseline parameters ({current} vs mean {mean})."

        qualifier = "significantly" if severity == AnomalySeverity.ANOMALOUS else "moderately"
        dir_text = "above" if direction == SignalDirection.HIGHER_THAN_BASELINE else "below"

        if metric == "predicted_legitimate_rps":
            return f"Legitimate demand is {qualifier} {dir_text} recent baseline ({current:.1f} vs mean {mean:.1f} RPS)."
        elif metric == "traffic_risk":
            return f"Traffic security risk is {qualifier} {dir_text} recent baseline ({current:.2f} vs mean {mean:.2f})."
        elif metric == "current_capacity_rps":
            return f"Current cluster processing capacity is {qualifier} {dir_text} recent baseline ({current:.1f} vs mean {mean:.1f} RPS)."
        elif metric == "recommended_pods":
            return f"SentinelScale recommended replicas are {qualifier} {dir_text} recent baseline ({int(current)} vs mean {mean:.1f} pods)."
        elif metric == "pod_delta_vs_baseline":
            return f"SentinelScale vs reactive HPA divergence is {qualifier} {dir_text} recent baseline delta ({int(current)} vs mean {mean:.1f} pods)."
        else:
            return f"{metric} is {qualifier} {dir_text} recent baseline ({current} vs mean {mean})."

    def assess_anomalies(
        self,
        current_values: Dict[str, float],
        window: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        observation_context: Optional[StoredObservation] = None,
    ) -> AnomalyAssessment:
        """
        Assess current metric values against historical baselines over the requested time window.
        """
        start_dt, end_dt, window_name = parse_and_validate_time_window(window, start_time, end_time)
        historical_records = self._history_store.get_observations_in_range(
            start_time=start_dt.isoformat(),
            end_time=end_dt.isoformat(),
        )

        total_samples = len(historical_records)
        baselines = self._baseline_service.extract_baselines_from_observations(historical_records)

        now_iso = datetime.now(timezone.utc).isoformat()

        # Handle global cold start
        if total_samples < self.min_samples:
            return AnomalyAssessment(
                generated_at=now_iso,
                baseline_window=window_name,
                start_time=start_dt.isoformat(),
                end_time=end_dt.isoformat(),
                sample_count=total_samples,
                minimum_required_samples=self.min_samples,
                overall_severity=AnomalySeverity.INSUFFICIENT_DATA,
                anomalous_signal_count=0,
                elevated_signal_count=0,
                signals=[],
                explanation=f"Insufficient baseline history ({total_samples}/{self.min_samples} required observation samples).",
                pattern_notes=["Baseline statistical confidence requires at least 5 historical observation cycles."],
            )

        evaluated_signals: List[AnomalySignal] = []
        for m_name, curr_val in current_values.items():
            if curr_val is None:
                continue
            if m_name in baselines:
                b = baselines[m_name]
                sig = self._score_signal(m_name, float(curr_val), b)
                evaluated_signals.append(sig)

        anomalous_count = sum(1 for s in evaluated_signals if s.severity == AnomalySeverity.ANOMALOUS)
        elevated_count = sum(1 for s in evaluated_signals if s.severity == AnomalySeverity.ELEVATED)

        if anomalous_count > 0:
            overall = AnomalySeverity.ANOMALOUS
            explanation = f"Detected {anomalous_count} anomalous signal(s) relative to historical baseline."
        elif elevated_count > 0:
            overall = AnomalySeverity.ELEVATED
            explanation = f"Detected {elevated_count} elevated signal(s) requiring observation."
        else:
            overall = AnomalySeverity.NORMAL
            explanation = "All evaluated signals are operating within expected historical baseline bounds."

        # Domain pattern notes
        pattern_notes: List[str] = []
        if observation_context and observation_context.success:
            if (
                observation_context.traffic_risk is not None
                and observation_context.traffic_risk >= 0.70
                and observation_context.action
                and observation_context.action.value == "HOLD"
            ):
                pattern_notes.append(
                    "Security mitigation active: Elevated traffic risk detected with legitimate demand fitting current capacity."
                )

        return AnomalyAssessment(
            generated_at=now_iso,
            baseline_window=window_name,
            start_time=start_dt.isoformat(),
            end_time=end_dt.isoformat(),
            sample_count=total_samples,
            minimum_required_samples=self.min_samples,
            overall_severity=overall,
            anomalous_signal_count=anomalous_count,
            elevated_signal_count=elevated_count,
            signals=evaluated_signals,
            explanation=explanation,
            pattern_notes=pattern_notes if pattern_notes else None,
        )

