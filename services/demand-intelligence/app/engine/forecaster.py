"""
SentinelScale — Demand Intelligence — Deterministic Forecasting Engine
Produces a DemandForecast from preprocessed observations.

Algorithm: Recency-Weighted Moving Average + Linear Trend Projection

Design principles:
- Deterministic: same input always produces the same output.
- Explainable: the algorithm is straightforward linear statistics, not a
  black-box ML model.
- Bounded: predicted RPS is always >= 0; lower_bound <= predicted <= upper_bound.
- Confidence is earned, not assigned arbitrarily:
    * More samples → higher confidence.
    * Lower variance → higher confidence.
    * Fewer samples → lower confidence with explicit floor.
- Never silently converts no-data into zero-demand.

The engine is intentionally kept simple (demand-v1). It does not require
Prometheus, Kubernetes, or any external infrastructure.
"""
import math
import uuid
from datetime import datetime, timezone
from typing import List

from app.models.demand import DemandForecast, DemandObservation
from app.engine.preprocessor import preprocess_observations, compute_statistics
from app.errors import InsufficientDataError, ForecastCalculationError
from app.config.settings import settings

# Minimum observations required to produce a forecast with any meaningful confidence.
MIN_OBSERVATIONS_FOR_FORECAST = 2

# Minimum observations before we apply trend extrapolation.
# With fewer samples the trend estimate is too noisy to trust.
MIN_OBSERVATIONS_FOR_TREND = 5

# Weight decay per step (oldest gets lowest weight). Must be in (0, 1).
RECENCY_WEIGHT_DECAY = 0.85

# Confidence scaling constants
_SAMPLE_CONFIDENCE_SCALE = 30   # ~30 samples → full sample contribution
_VARIANCE_CONFIDENCE_SCALE = 0.15  # 15% CV → zero variance contribution

# Prediction interval half-width multiplier (±1.5 std-dev ≈ ~87% coverage)
INTERVAL_HALF_WIDTH_SIGMA = 1.5


def _weighted_mean(values: List[float], decay: float = RECENCY_WEIGHT_DECAY) -> float:
    """
    Recency-weighted mean. The most recent value has weight 1.0,
    each predecessor is multiplied by `decay`.
    """
    n = len(values)
    total_weight = 0.0
    weighted_sum = 0.0
    for i, v in enumerate(values):
        weight = decay ** (n - 1 - i)
        weighted_sum += v * weight
        total_weight += weight
    return weighted_sum / total_weight if total_weight > 0 else 0.0


def _compute_confidence(
    n_samples: int,
    mean_rps: float,
    std_dev_rps: float,
) -> float:
    """
    Compute a [0.0, 1.0] confidence score.

    Factors:
    1. Sample confidence: saturates towards 1.0 as sample count grows.
    2. Variance confidence: lower coefficient of variation → higher confidence.
       If mean is zero we assume low confidence (can't assess relative variance).
    """
    # Sample confidence: sigmoid-like, saturates at _SAMPLE_CONFIDENCE_SCALE samples
    sample_conf = 1.0 - math.exp(-n_samples / _SAMPLE_CONFIDENCE_SCALE)

    # Variance confidence: based on coefficient of variation (CV = std/mean)
    if mean_rps > 0:
        cv = std_dev_rps / mean_rps
        variance_conf = math.exp(-cv / _VARIANCE_CONFIDENCE_SCALE)
    else:
        variance_conf = 0.1  # very low confidence when mean is zero

    # Combined: geometric mean so both factors contribute multiplicatively
    confidence = math.sqrt(sample_conf * variance_conf)
    return round(min(1.0, max(0.0, confidence)), 4)


def _project_demand(
    weighted_mean_rps: float,
    trend_slope: float,
    horizon_seconds: int,
    n_samples: int,
) -> float:
    """
    Project demand forward by `horizon_seconds` using the current trend slope.
    Trend is only applied when there are enough samples to trust it.
    Returns a value clamped to >= 0.
    """
    if n_samples >= MIN_OBSERVATIONS_FOR_TREND:
        projected = weighted_mean_rps + trend_slope * horizon_seconds
    else:
        projected = weighted_mean_rps  # no trend extrapolation with sparse data

    return max(0.0, projected)


def produce_forecast(
    observations: List[DemandObservation],
    forecast_horizon_seconds: int,
    trace_id: str | None = None,
) -> DemandForecast:
    """
    Produce a DemandForecast from a list of demand observations.

    Args:
        observations: Raw (unsorted, potentially invalid) observation list.
        forecast_horizon_seconds: How far forward to project.
        trace_id: Optional trace ID to propagate into the forecast event.

    Returns:
        DemandForecast conforming to contracts/demand/demand_forecast.schema.json v1.0.0.

    Raises:
        InsufficientDataError: If fewer than MIN_OBSERVATIONS_FOR_FORECAST
            valid observations are available.
        InvalidObservationError: If any observation contains invalid data.
        ForecastCalculationError: On unexpected calculation failures.
    """
    # Step 1: Preprocess (validate, sort, deduplicate)
    cleaned = preprocess_observations(observations)

    if len(cleaned) < MIN_OBSERVATIONS_FOR_FORECAST:
        raise InsufficientDataError(
            required=MIN_OBSERVATIONS_FOR_FORECAST,
            available=len(cleaned),
        )

    # Step 2: Compute statistics on clean observations
    mean_rps, std_dev_rps, trend_slope = compute_statistics(cleaned)

    # Step 3: Weighted mean (recency-biased point estimate)
    values = [o.rps for o in cleaned]
    w_mean = _weighted_mean(values)

    # Step 4: Project forward using trend (if enough data)
    n = len(cleaned)
    predicted = _project_demand(w_mean, trend_slope, forecast_horizon_seconds, n)

    # Step 5: Prediction interval (based on historical std-dev)
    half_width = INTERVAL_HALF_WIDTH_SIGMA * std_dev_rps
    lower = max(0.0, predicted - half_width)
    upper = predicted + half_width

    # Sanity guard: ensure lower <= predicted <= upper
    lower = min(lower, predicted)
    upper = max(upper, predicted)

    # Step 6: Confidence
    confidence = _compute_confidence(n, mean_rps, std_dev_rps)

    # Step 7: Build the frozen contract object
    effective_trace_id = trace_id or f"trace-{uuid.uuid4().hex[:16]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        return DemandForecast(
            event_id=str(uuid.uuid4()),
            trace_id=effective_trace_id,
            generated_at=now_iso,
            contract_version=settings.CONTRACT_VERSION,
            service_version=settings.SERVICE_VERSION,
            model_version=settings.MODEL_VERSION,
            forecast_horizon_seconds=forecast_horizon_seconds,
            predicted_legitimate_rps=round(predicted, 4),
            lower_bound_rps=round(lower, 4),
            upper_bound_rps=round(upper, 4),
            confidence=confidence,
        )
    except Exception as exc:
        raise ForecastCalculationError(
            f"Failed to construct DemandForecast contract object: {exc}"
        ) from exc
