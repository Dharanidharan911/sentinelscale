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

def _weighted_mean(
    observations: List[DemandObservation], 
    decay: float | None = None, 
    ref_interval: float | None = None
) -> float:
    """
    Time-aware recency-weighted mean. The most recent value has weight 1.0,
    and older values decay exponentially based on the time difference.
    """
    if not observations:
        return 0.0
        
    decay = decay if decay is not None else settings.FORECAST_RECENCY_WEIGHT_DECAY
    ref_interval = ref_interval if ref_interval is not None else settings.FORECAST_RECENCY_REFERENCE_INTERVAL_SECONDS

    t_last = observations[-1].timestamp
    total_weight = 0.0
    weighted_sum = 0.0
    
    for obs in observations:
        # Number of reference intervals in the past
        intervals_ago = max(0.0, (t_last - obs.timestamp) / ref_interval)
        weight = decay ** intervals_ago
        weighted_sum += obs.rps * weight
        total_weight += weight
        
    return weighted_sum / total_weight if total_weight > 0 else 0.0


def _compute_confidence(
    n_samples: int,
    mean_rps: float,
    std_dev_rps: float,
    time_span: float,
    horizon: int,
    sampling_regularity: float = 1.0,
) -> float:
    """
    Compute a [0.0, 1.0] confidence score.

    Factors:
    1. Sample confidence: saturates towards 1.0 as sample count grows.
    2. Variance confidence: lower coefficient of variation → higher confidence.
    3. Horizon confidence: penalizes forecasting far beyond historical time span.
    """
    # Sample confidence: sigmoid-like, saturates at FORECAST_SAMPLE_CONFIDENCE_SCALE samples
    sample_conf = 1.0 - math.exp(-n_samples / settings.FORECAST_SAMPLE_CONFIDENCE_SCALE)

    # Variance confidence: based on coefficient of variation (CV = std/mean)
    if mean_rps > 0:
        cv = std_dev_rps / mean_rps
        variance_conf = math.exp(-cv / settings.FORECAST_VARIANCE_CONFIDENCE_SCALE)
    else:
        variance_conf = 0.1  # very low confidence when mean is zero
        
    # Horizon confidence: soft penalty if time_span is short relative to horizon
    horizon_ratio = time_span / float(horizon) if horizon > 0 else 1.0
    horizon_conf = min(1.0, horizon_ratio * 1.5)

    # Irregular but valid sampling reduces certainty rather than invalidating
    # the data. 0 is maximally irregular; 1 is perfectly regular.
    regularity_conf = math.exp(
        -(1.0 - max(0.0, min(1.0, sampling_regularity)))
        / settings.FORECAST_REGULARITY_CONFIDENCE_SCALE
    )
    confidence = (sample_conf * variance_conf * horizon_conf * regularity_conf) ** (1/4)
    return round(min(1.0, max(0.0, confidence)), 4)


def _sampling_regularity(observations: List[DemandObservation]) -> float:
    """Return a deterministic [0, 1] cadence-regularity score."""
    if len(observations) < 3:
        return 1.0
    intervals = [
        observations[index].timestamp - observations[index - 1].timestamp
        for index in range(1, len(observations))
    ]
    mean_interval = sum(intervals) / len(intervals)
    if mean_interval <= 0:
        return 0.0
    variance = sum((value - mean_interval) ** 2 for value in intervals) / len(intervals)
    coefficient_of_variation = math.sqrt(variance) / mean_interval
    return 1.0 / (1.0 + coefficient_of_variation)


def _project_demand(
    weighted_mean_rps: float,
    trend_slope: float,
    horizon_seconds: int,
    n_samples: int,
    time_span: float,
) -> float:
    """
    Project demand forward by `horizon_seconds` using the current trend slope.
    Trend is only applied when there are enough samples spanning a sufficient time
    window to trust it. The slope is capped to prevent explosive projections.
    Returns a value clamped to >= 0.
    """
    if (n_samples >= settings.FORECAST_MIN_OBSERVATIONS_FOR_TREND and 
        time_span >= settings.FORECAST_MIN_TIME_SPAN_FOR_TREND):
        max_slope = settings.FORECAST_MAX_TREND_SLOPE
        safe_slope = max(-max_slope, min(max_slope, trend_slope))
        projected = weighted_mean_rps + safe_slope * horizon_seconds
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

    if len(cleaned) < settings.FORECAST_MIN_OBSERVATIONS:
        raise InsufficientDataError(
            required=settings.FORECAST_MIN_OBSERVATIONS,
            available=len(cleaned),
        )

    # Calculate total time span of observations
    time_span = cleaned[-1].timestamp - cleaned[0].timestamp

    # Step 2: Compute statistics on clean observations
    mean_rps, std_dev_rps, trend_slope = compute_statistics(cleaned)

    # Step 3: Weighted mean (time-aware recency-biased point estimate)
    w_mean = _weighted_mean(cleaned)

    # Step 4: Project forward using trend (if enough data and time span)
    n = len(cleaned)
    predicted = _project_demand(w_mean, trend_slope, forecast_horizon_seconds, n, time_span)

    # Step 5: Prediction interval (based on historical std-dev)
    half_width = settings.FORECAST_INTERVAL_HALF_WIDTH_SIGMA * std_dev_rps
    lower = max(0.0, predicted - half_width)
    upper = predicted + half_width

    # Sanity guard: ensure lower <= predicted <= upper
    lower = min(lower, predicted)
    upper = max(upper, predicted)

    # Step 6: Confidence
    confidence = _compute_confidence(
        n, mean_rps, std_dev_rps, time_span, forecast_horizon_seconds,
        _sampling_regularity(cleaned),
    )

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
