"""
SentinelScale — Demand Intelligence — Observation Preprocessor
Validates, cleans, and normalises raw observations before forecasting.

Preprocessing rules:
1. Reject observations with negative RPS (invalid — raise explicitly).
2. Sort by timestamp (oldest first).
3. Deduplicate: if two observations share the same timestamp, keep the last.
4. Report empty result explicitly — callers must handle the no-data case.

This layer is purely functional. It does not produce forecasts.
It does not silently discard all data and pretend demand is zero.
"""
from typing import List, Tuple

from app.models.demand import DemandObservation
from app.errors import InvalidObservationError


def preprocess_observations(
    raw: List[DemandObservation],
) -> List[DemandObservation]:
    """
    Validate and normalise a list of demand observations.

    Args:
        raw: Unordered, potentially invalid list of observations.

    Returns:
        Cleaned list of DemandObservation, sorted oldest-first, deduplicated.
        May be empty if raw is empty.

    Raises:
        InvalidObservationError: If any observation has a negative RPS value.
    """
    if not raw:
        return []

    # Validate all observations first — fail fast on invalid data
    for obs in raw:
        if obs.rps < 0:
            raise InvalidObservationError(
                f"Observation at timestamp {obs.timestamp} has negative RPS: {obs.rps}. "
                f"Negative demand is physically impossible."
            )

    # Sort oldest → newest
    sorted_obs = sorted(raw, key=lambda o: o.timestamp)

    # Deduplicate by timestamp: keep the last occurrence (most recent write wins)
    seen: dict[float, DemandObservation] = {}
    for obs in sorted_obs:
        seen[obs.timestamp] = obs

    return list(seen.values())  # dict preserves insertion order (Python 3.7+)


def compute_statistics(
    observations: List[DemandObservation],
) -> Tuple[float, float, float]:
    """
    Compute mean, standard deviation, and linear trend slope of a series.

    Args:
        observations: Non-empty, sorted list of DemandObservation objects.

    Returns:
        Tuple of (mean_rps, std_dev_rps, trend_slope_rps_per_second).
        trend_slope > 0 means rising demand, < 0 means falling.
    """
    n = len(observations)
    values = [o.rps for o in observations]

    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std_dev = variance ** 0.5

    if n < 2:
        return mean, std_dev, 0.0

    # Linear regression slope via least-squares
    timestamps = [o.timestamp for o in observations]
    t_mean = sum(timestamps) / n
    numerator = sum(
        (timestamps[i] - t_mean) * (values[i] - mean)
        for i in range(n)
    )
    denominator = sum((t - t_mean) ** 2 for t in timestamps)
    slope = numerator / denominator if denominator != 0 else 0.0

    return mean, std_dev, slope
