from datetime import datetime, timedelta, timezone
import math
from typing import Dict, List, Optional, Tuple
from app.config.settings import settings
from app.models.history import StoredObservation
from app.models.prediction import (
    ConfidenceLevel,
    DataQuality,
    PredictionStatus,
    PredictiveForecast,
    PredictivePodAdvisory,
    PredictivePressure,
    PressureLevel,
    SignalForecast,
    TrendDirection,
)
from app.services.history.base import DecisionHistoryStore
from app.services.intelligence.historical import parse_and_validate_time_window
from app.services.intelligence.predictive_base import PredictiveIntelligenceService

SUPPORTED_HORIZONS: Dict[str, int] = {
    "30s": 30,
    "1m": 60,
    "5m": 300,
    "15m": 900,
}

MINIMUM_PREDICTION_SAMPLES: int = 5
MAX_RECENCY_STALE_SECONDS: int = 600  # 10 minutes


def parse_and_validate_horizon(
    horizon: Optional[str] = None,
    horizon_seconds: Optional[int] = None,
) -> int:
    """
    Resolve and validate forecasting horizon parameters.
    Returns horizon in seconds.
    Raises ValueError on invalid horizon format or out-of-bounds values.
    """
    if horizon is not None:
        norm_horizon = horizon.strip().lower()
        if norm_horizon not in SUPPORTED_HORIZONS:
            supported = ", ".join(SUPPORTED_HORIZONS.keys())
            raise ValueError(f"Invalid horizon '{horizon}'. Supported horizons: {supported}")
        return SUPPORTED_HORIZONS[norm_horizon]

    if horizon_seconds is not None:
        if horizon_seconds < 10 or horizon_seconds > 3600:
            raise ValueError(f"horizon_seconds ({horizon_seconds}) must be between 10 and 3600 seconds.")
        return horizon_seconds

    # Default horizon: 5 minutes (300s)
    return 300


class DefaultPredictiveIntelligenceService(PredictiveIntelligenceService):
    """
    Deterministic Short-Horizon Predictive Intelligence Service.
    Applies Ordinary Least Squares (OLS) trend fitting to recent historical observations
    and calculates capacity pressure and advisory pod requirements.
    """

    def __init__(
        self,
        history_store: DecisionHistoryStore,
        min_samples: int = MINIMUM_PREDICTION_SAMPLES,
    ):
        self._history_store = history_store
        self.min_samples = min_samples

    def _fit_ols_trend(
        self,
        points: List[Tuple[float, float]],
        horizon_seconds: int,
    ) -> Tuple[float, float, float, float, float, float]:
        """
        Fit linear trend y = a + b*x via Ordinary Least Squares.
        Points: [(elapsed_seconds_from_t0, value_y)]
        Returns: (slope_b, intercept_a, mean_y, raw_predicted_future, r_squared, has_outlier)
        """
        n = len(points)
        x_vals = [p[0] for p in points]
        y_vals = [p[1] for p in points]

        mean_x = sum(x_vals) / n
        mean_y = sum(y_vals) / n

        var_x = sum((x - mean_x) ** 2 for x in x_vals)
        var_y = sum((y - mean_y) ** 2 for y in y_vals) / n

        if var_x < 1e-6:
            slope_b = 0.0
            intercept_a = mean_y
        else:
            cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in points)
            slope_b = cov_xy / var_x
            intercept_a = mean_y - slope_b * mean_x

        latest_x = x_vals[-1]
        future_x = latest_x + float(horizon_seconds)
        pred_future = intercept_a + slope_b * future_x

        # Residuals analysis for goodness-of-fit & outlier resistance
        residuals = [y - (intercept_a + slope_b * x) for x, y in points]
        ss_res = sum(r ** 2 for r in residuals)
        ss_tot = sum((y - mean_y) ** 2 for y in y_vals)

        r_squared = 1.0 if ss_tot < 1e-6 else max(0.0, 1.0 - (ss_res / ss_tot))

        # Check for extreme residuals (> 3 * std_dev of residuals)
        res_std = math.sqrt(ss_res / n) if n > 0 else 0.0
        has_outlier = any(abs(r) > 3.0 * res_std for r in residuals) if res_std > 1e-4 else False

        return slope_b, intercept_a, mean_y, pred_future, r_squared, has_outlier

    def _forecast_signal(
        self,
        signal_name: str,
        points: List[Tuple[float, float]],
        horizon_seconds: int,
        is_stale: bool,
    ) -> SignalForecast:
        n = len(points)
        if n < self.min_samples:
            return SignalForecast(
                signal=signal_name,
                status=PredictionStatus.INSUFFICIENT_DATA,
                sample_count=n,
                trend=TrendDirection.INSUFFICIENT_DATA,
                confidence=ConfidenceLevel.INSUFFICIENT_DATA,
                forecast_horizon_seconds=horizon_seconds,
                interpretation=f"Insufficient historical samples ({n}/{self.min_samples} required).",
            )

        latest_val = points[-1][1]
        slope_b, intercept_a, mean_y, raw_pred, r_sq, has_outlier = self._fit_ols_trend(points, horizon_seconds)

        # Clamping to valid domain
        if signal_name == "traffic_risk":
            clamped_pred = min(1.0, max(0.0, raw_pred))
        elif signal_name in {"recommended_pods", "current_pods", "baseline_hpa_recommended_pods"}:
            clamped_pred = max(1.0, raw_pred)
        elif signal_name == "pod_delta_vs_baseline":
            clamped_pred = raw_pred  # Can be negative
        else:
            clamped_pred = max(0.0, raw_pred)

        delta = round(clamped_pred - latest_val, 2)
        delta_pct = round((delta / abs(latest_val)) * 100.0, 1) if abs(latest_val) > 1e-4 else 0.0

        # Classify trend direction
        if signal_name == "traffic_risk":
            if abs(delta) < 0.02:
                trend = TrendDirection.STABLE
            elif delta > 0:
                trend = TrendDirection.INCREASING
            else:
                trend = TrendDirection.DECREASING
        else:
            if abs(delta) < 0.5 or abs(delta_pct) < 2.0:
                trend = TrendDirection.STABLE
            elif delta > 0:
                trend = TrendDirection.INCREASING
            else:
                trend = TrendDirection.DECREASING

        # Determine confidence
        if is_stale:
            confidence = ConfidenceLevel.LOW
            status = PredictionStatus.STALE
        elif n >= 10 and r_sq >= 0.50 and not has_outlier:
            confidence = ConfidenceLevel.HIGH
            status = PredictionStatus.OK
        elif n >= self.min_samples and not has_outlier:
            confidence = ConfidenceLevel.MEDIUM
            status = PredictionStatus.OK
        else:
            confidence = ConfidenceLevel.LOW
            status = PredictionStatus.DEGRADED

        # Generate interpretation
        if trend == TrendDirection.STABLE:
            interp = f"{signal_name} is projected to remain stable at ~{clamped_pred:.1f} over the next {horizon_seconds}s."
        elif trend == TrendDirection.INCREASING:
            interp = f"{signal_name} is projected to increase by +{delta:.1f} ({delta_pct:+.1f}%) to {clamped_pred:.1f} over the next {horizon_seconds}s."
        else:
            interp = f"{signal_name} is projected to decrease by {delta:.1f} ({delta_pct:+.1f}%) to {clamped_pred:.1f} over the next {horizon_seconds}s."

        return SignalForecast(
            signal=signal_name,
            status=status,
            sample_count=n,
            latest_value=round(latest_val, 2),
            predicted_value=round(clamped_pred, 2),
            delta=delta,
            delta_percent=delta_pct,
            trend=trend,
            confidence=confidence,
            mean=round(mean_y, 2),
            slope_per_second=round(slope_b, 4),
            forecast_horizon_seconds=horizon_seconds,
            interpretation=interp,
        )

    def generate_forecast(
        self,
        window: Optional[str] = None,
        horizon: Optional[str] = None,
        horizon_seconds: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        observation_id: Optional[str] = None,
        current_values: Optional[Dict[str, float]] = None,
    ) -> PredictiveForecast:
        return self.forecast(
            window=window,
            horizon=horizon,
            horizon_seconds=horizon_seconds,
            start_time=start_time,
            end_time=end_time,
            observation_id=observation_id,
            current_values=current_values,
        )

    def forecast(
        self,
        window: Optional[str] = None,
        horizon: Optional[str] = None,
        horizon_seconds: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        observation_id: Optional[str] = None,
        current_values: Optional[Dict[str, float]] = None,
    ) -> PredictiveForecast:
        start_dt, end_dt, window_name = parse_and_validate_time_window(window, start_time, end_time)
        target_horizon_sec = parse_and_validate_horizon(horizon, horizon_seconds)

        if observation_id:
            target_obs = self._history_store.get_observation(observation_id)
            if not target_obs:
                raise ValueError(f"Observation '{observation_id}' not found in history.")

        historical_records = self._history_store.get_observations_in_range(
            start_time=start_dt.isoformat(),
            end_time=end_dt.isoformat(),
        )

        successful_obs = [o for o in historical_records if o.success]
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        # Handle global cold start
        if len(successful_obs) < self.min_samples:
            return PredictiveForecast(
                generated_at=now_iso,
                baseline_window=window_name,
                start_time=start_dt.isoformat(),
                end_time=end_dt.isoformat(),
                forecast_horizon_seconds=target_horizon_sec,
                status=PredictionStatus.INSUFFICIENT_DATA,
                data_quality=DataQuality.INSUFFICIENT_DATA,
                sample_count=len(successful_obs),
                minimum_required_samples=self.min_samples,
                latest_observation_time=successful_obs[-1].timestamp if successful_obs else None,
                signals={},
                pressure=PredictivePressure(
                    predicted_legitimate_rps=None,
                    predicted_capacity_rps=None,
                    predicted_capacity_utilization=None,
                    level=PressureLevel.INSUFFICIENT_DATA,
                    interpretation="Insufficient historical data to forecast capacity pressure.",
                ),
                pods=PredictivePodAdvisory(
                    predicted_recommended_pods=None,
                    predicted_hpa_pods=None,
                    predicted_delta_vs_hpa=None,
                    min_pods=settings.DEFAULT_MIN_PODS,
                    max_pods=settings.DEFAULT_MAX_PODS,
                    interpretation="Insufficient historical data to project advisory replica requirements.",
                ),
                explanation=f"Insufficient observation history ({len(successful_obs)}/{self.min_samples} required samples) for forecasting.",
            )

        # Parse observation timestamps and check recency
        parsed_obs: List[Tuple[datetime, StoredObservation]] = []
        for o in successful_obs:
            try:
                obs_dt = datetime.fromisoformat(o.timestamp.replace("Z", "+00:00"))
                if obs_dt.tzinfo is None:
                    obs_dt = obs_dt.replace(tzinfo=timezone.utc)
                parsed_obs.append((obs_dt, o))
            except Exception:
                continue

        parsed_obs.sort(key=lambda x: x[0])
        t0 = parsed_obs[0][0]
        latest_obs_dt = parsed_obs[-1][0]
        recency_delta = (now_dt - latest_obs_dt).total_seconds()
        is_stale = recency_delta > MAX_RECENCY_STALE_SECONDS

        # Extract per-signal time-series points: (elapsed_seconds, value)
        raw_signals: Dict[str, List[Tuple[float, float]]] = {
            "predicted_legitimate_rps": [],
            "traffic_risk": [],
            "current_capacity_rps": [],
            "recommended_pods": [],
            "current_pods": [],
            "baseline_hpa_recommended_pods": [],
            "pod_delta_vs_baseline": [],
        }

        for dt, o in parsed_obs:
            elapsed = (dt - t0).total_seconds()
            if o.predicted_legitimate_rps is not None:
                raw_signals["predicted_legitimate_rps"].append((elapsed, float(o.predicted_legitimate_rps)))
            if o.traffic_risk is not None:
                raw_signals["traffic_risk"].append((elapsed, float(o.traffic_risk)))
            if o.current_capacity_rps is not None:
                raw_signals["current_capacity_rps"].append((elapsed, float(o.current_capacity_rps)))
            if o.recommended_pods is not None:
                raw_signals["recommended_pods"].append((elapsed, float(o.recommended_pods)))
            if o.current_pods is not None:
                raw_signals["current_pods"].append((elapsed, float(o.current_pods)))
            if o.baseline_hpa_recommended_pods is not None:
                raw_signals["baseline_hpa_recommended_pods"].append((elapsed, float(o.baseline_hpa_recommended_pods)))
            if o.pod_delta_vs_baseline is not None:
                raw_signals["pod_delta_vs_baseline"].append((elapsed, float(o.pod_delta_vs_baseline)))

        forecasted_signals: Dict[str, SignalForecast] = {}
        for s_name, pts in raw_signals.items():
            if pts:
                sf = self._forecast_signal(s_name, pts, target_horizon_sec, is_stale)
                forecasted_signals[s_name] = sf

        # Derive capacity pressure
        pred_demand = forecasted_signals.get("predicted_legitimate_rps")
        pred_cap = forecasted_signals.get("current_capacity_rps")

        if (
            pred_demand
            and pred_demand.predicted_value is not None
            and pred_cap
            and pred_cap.predicted_value is not None
            and pred_cap.predicted_value > 0
        ):
            pred_demand_val = pred_demand.predicted_value
            pred_cap_val = pred_cap.predicted_value
            utilization = round(pred_demand_val / pred_cap_val, 3)

            if utilization >= 0.90:
                p_level = PressureLevel.CRITICAL
                p_interp = f"Forecasted demand ({pred_demand_val:.1f} RPS) creates CRITICAL pressure ({utilization * 100:.1f}% utilization) on capacity ({pred_cap_val:.1f} RPS)."
            elif utilization >= 0.75:
                p_level = PressureLevel.HIGH
                p_interp = f"Forecasted demand ({pred_demand_val:.1f} RPS) creates HIGH pressure ({utilization * 100:.1f}% utilization) on capacity ({pred_cap_val:.1f} RPS)."
            elif utilization >= 0.50:
                p_level = PressureLevel.ELEVATED
                p_interp = f"Forecasted demand ({pred_demand_val:.1f} RPS) creates ELEVATED pressure ({utilization * 100:.1f}% utilization) on capacity ({pred_cap_val:.1f} RPS)."
            else:
                p_level = PressureLevel.NORMAL
                p_interp = f"Forecasted demand ({pred_demand_val:.1f} RPS) is well within capacity ({pred_cap_val:.1f} RPS, {utilization * 100:.1f}% utilization)."

            pressure = PredictivePressure(
                predicted_legitimate_rps=pred_demand_val,
                predicted_capacity_rps=pred_cap_val,
                predicted_capacity_utilization=utilization,
                level=p_level,
                interpretation=p_interp,
            )
        else:
            pressure = PredictivePressure(
                predicted_legitimate_rps=pred_demand.predicted_value if pred_demand else None,
                predicted_capacity_rps=pred_cap.predicted_value if pred_cap else None,
                predicted_capacity_utilization=None,
                level=PressureLevel.INSUFFICIENT_DATA,
                interpretation="Capacity pressure could not be calculated due to missing demand/capacity signals.",
            )

        # Derive advisory pod requirements using capacity-per-pod semantics
        pod_rps_cap = settings.DEFAULT_POD_RPS_CAPACITY
        min_p = settings.DEFAULT_MIN_PODS
        max_p = settings.DEFAULT_MAX_PODS

        if pred_demand and pred_demand.predicted_value is not None:
            raw_req_pods = math.ceil(pred_demand.predicted_value / pod_rps_cap)
            advisory_rec_pods = min(max(raw_req_pods, min_p), max_p)
        else:
            advisory_rec_pods = None

        pred_hpa = forecasted_signals.get("baseline_hpa_recommended_pods")
        if pred_hpa and pred_hpa.predicted_value is not None:
            advisory_hpa_pods = max(1, round(pred_hpa.predicted_value))
        else:
            advisory_hpa_pods = None

        if advisory_rec_pods is not None and advisory_hpa_pods is not None:
            delta_vs_hpa = advisory_rec_pods - advisory_hpa_pods
            if delta_vs_hpa > 0:
                hpa_interp = f"SentinelScale projects proactive requirement of {advisory_rec_pods} pods (HPA projected at {advisory_hpa_pods} pods; delta +{delta_vs_hpa} pods)."
            elif delta_vs_hpa < 0:
                hpa_interp = f"SentinelScale projects conservative requirement of {advisory_rec_pods} pods (HPA projected at {advisory_hpa_pods} pods; suppressed overprovisioning of {abs(delta_vs_hpa)} pods)."
            else:
                hpa_interp = f"SentinelScale and HPA forecasts are aligned at {advisory_rec_pods} pods."
        else:
            delta_vs_hpa = None
            hpa_interp = "Advisory pod requirements could not be fully compared against HPA baseline."

        pod_advisory = PredictivePodAdvisory(
            predicted_recommended_pods=advisory_rec_pods,
            predicted_hpa_pods=advisory_hpa_pods,
            predicted_delta_vs_hpa=delta_vs_hpa,
            min_pods=min_p,
            max_pods=max_p,
            interpretation=hpa_interp,
        )

        # Data quality & overall status
        if is_stale:
            data_quality = DataQuality.STALE
            overall_status = PredictionStatus.STALE
            explanation = f"Forecast generated from STALE observations (latest observation was {recency_delta:.0f}s ago)."
        elif any(sf.status == PredictionStatus.DEGRADED for sf in forecasted_signals.values()):
            data_quality = DataQuality.DEGRADED
            overall_status = PredictionStatus.DEGRADED
            explanation = "Forecast generated with DEGRADED confidence due to high residual variance in historical signals."
        else:
            data_quality = DataQuality.GOOD
            overall_status = PredictionStatus.OK
            explanation = f"Forecast successfully computed across {len(forecasted_signals)} operational signals for horizon {target_horizon_sec}s."

        return PredictiveForecast(
            generated_at=now_iso,
            baseline_window=window_name,
            start_time=start_dt.isoformat(),
            end_time=end_dt.isoformat(),
            forecast_horizon_seconds=target_horizon_sec,
            status=overall_status,
            data_quality=data_quality,
            sample_count=len(successful_obs),
            minimum_required_samples=self.min_samples,
            latest_observation_time=parsed_obs[-1][1].timestamp,
            signals=forecasted_signals,
            pressure=pressure,
            pods=pod_advisory,
            explanation=explanation,
        )
