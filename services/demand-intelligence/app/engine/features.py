"""
SentinelScale — Demand Intelligence — Feature Engineering Layer (M2-4)
Extracts deterministic, leakage-safe statistical and time-series features
from cleaned DemandObservation sequences.

Principles:
1. Leakage-Safe: Every feature at index i is derived strictly from observations
   at indices <= i (no future information).
2. Deterministic: Same input observations and horizon always yield the identical
   feature vector.
3. Stable Ordering: Features have fixed, named keys and a canonical float vector
   representation.
4. Explicit Insufficient-History Semantics: Clear thresholds with explicit error
   raising or sparsity indicators when observation history is insufficient.
"""
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.models.demand import DemandObservation
from app.engine.preprocessor import preprocess_observations, compute_statistics
from app.errors import InsufficientDataError


FEATURE_NAMES: Tuple[str, ...] = (
    "recent_demand",
    "lag_1",
    "lag_2",
    "rolling_mean_short",
    "rolling_mean_full",
    "rolling_std_full",
    "trend_slope",
    "rate_of_change",
    "acceleration",
    "sampling_regularity",
    "time_span_seconds",
    "horizon_ratio",
)

# Minimum observations required to construct the full 3-lag feature set
MIN_OBSERVATIONS_FOR_FEATURES = 4


@dataclass(frozen=True)
class DemandFeatureVector:
    """Immutable, typed container for engineered demand time-series features."""
    recent_demand: float
    lag_1: float
    lag_2: float
    rolling_mean_short: float
    rolling_mean_full: float
    rolling_std_full: float
    trend_slope: float
    rate_of_change: float
    acceleration: float
    sampling_regularity: float
    time_span_seconds: float
    horizon_ratio: float

    def to_dict(self) -> Dict[str, float]:
        """Return features as a named dictionary."""
        return {
            "recent_demand": self.recent_demand,
            "lag_1": self.lag_1,
            "lag_2": self.lag_2,
            "rolling_mean_short": self.rolling_mean_short,
            "rolling_mean_full": self.rolling_mean_full,
            "rolling_std_full": self.rolling_std_full,
            "trend_slope": self.trend_slope,
            "rate_of_change": self.rate_of_change,
            "acceleration": self.acceleration,
            "sampling_regularity": self.sampling_regularity,
            "time_span_seconds": self.time_span_seconds,
            "horizon_ratio": self.horizon_ratio,
        }

    def to_list(self) -> List[float]:
        """Return feature values in canonical, stable order."""
        return [
            self.recent_demand,
            self.lag_1,
            self.lag_2,
            self.rolling_mean_short,
            self.rolling_mean_full,
            self.rolling_std_full,
            self.trend_slope,
            self.rate_of_change,
            self.acceleration,
            self.sampling_regularity,
            self.time_span_seconds,
            self.horizon_ratio,
        ]


def compute_cadence_regularity(observations: List[DemandObservation]) -> float:
    """
    Compute deterministic sampling cadence regularity score in [0.0, 1.0].
    1.0 means perfectly uniform sampling intervals; 0.0 means highly irregular.
    """
    if len(observations) < 3:
        return 1.0
    intervals = [
        observations[i].timestamp - observations[i - 1].timestamp
        for i in range(1, len(observations))
    ]
    mean_dt = sum(intervals) / len(intervals)
    if mean_dt <= 0.0:
        return 0.0
    var_dt = sum((dt - mean_dt) ** 2 for dt in intervals) / len(intervals)
    cv = math.sqrt(var_dt) / mean_dt
    return 1.0 / (1.0 + cv)


class DemandFeatureExtractor:
    """
    Extracts time-series feature representations for demand forecasting.
    Input observations are assumed to be validated and sorted oldest-first.
    """

    @classmethod
    def extract_features(
        cls,
        observations: List[DemandObservation],
        forecast_horizon_seconds: int,
    ) -> DemandFeatureVector:
        """
        Extract the canonical feature vector from preprocessed observations.

        Args:
            observations: Cleaned, sorted, deduplicated DemandObservation list.
            forecast_horizon_seconds: Horizon forward in seconds.

        Returns:
            DemandFeatureVector with stable feature names and ordering.

        Raises:
            InsufficientDataError: If len(observations) < MIN_OBSERVATIONS_FOR_FEATURES.
        """
        n = len(observations)
        if n < MIN_OBSERVATIONS_FOR_FEATURES:
            raise InsufficientDataError(
                required=MIN_OBSERVATIONS_FOR_FEATURES,
                available=n,
            )

        values = [o.rps for o in observations]
        timestamps = [o.timestamp for o in observations]

        # 1. Recent demand and lags
        recent = values[-1]
        lag_1 = values[-2]
        lag_2 = values[-3]

        # 2. Rolling statistics
        short_window = values[-3:]
        rolling_mean_short = sum(short_window) / len(short_window)

        rolling_mean_full, rolling_std_full, trend_slope = compute_statistics(observations)

        # 3. Rate of change and acceleration
        dt_1 = max(0.1, timestamps[-1] - timestamps[-2])
        dt_2 = max(0.1, timestamps[-2] - timestamps[-3])
        roc_1 = (values[-1] - values[-2]) / dt_1
        roc_2 = (values[-2] - values[-3]) / dt_2
        acceleration = (roc_1 - roc_2) / ((dt_1 + dt_2) / 2.0)

        # 4. Temporal and cadence features
        time_span = max(0.1, timestamps[-1] - timestamps[0])
        regularity = compute_cadence_regularity(observations)
        horizon_ratio = float(forecast_horizon_seconds) / max(30.0, time_span)

        return DemandFeatureVector(
            recent_demand=round(recent, 4),
            lag_1=round(lag_1, 4),
            lag_2=round(lag_2, 4),
            rolling_mean_short=round(rolling_mean_short, 4),
            rolling_mean_full=round(rolling_mean_full, 4),
            rolling_std_full=round(rolling_std_full, 4),
            trend_slope=round(trend_slope, 6),
            rate_of_change=round(roc_1, 6),
            acceleration=round(acceleration, 6),
            sampling_regularity=round(regularity, 4),
            time_span_seconds=round(time_span, 2),
            horizon_ratio=round(horizon_ratio, 4),
        )

    @classmethod
    def extract_training_dataset(
        cls,
        observations: List[DemandObservation],
        horizon_steps: int = 1,
    ) -> Tuple[List[List[float]], List[float]]:
        """
        Construct a leakage-safe supervised training dataset (X, y) from historical observations.
        For each point t, features are extracted from observations up to t, and target is
        the observation at t + horizon_steps.

        Returns:
            Tuple of (feature_matrix X, target_vector y).
        """
        n = len(observations)
        min_required = MIN_OBSERVATIONS_FOR_FEATURES + horizon_steps
        if n < min_required:
            return [], []

        X: List[List[float]] = []
        y: List[float] = []

        # Target step timestamp distance for horizon
        for end_idx in range(MIN_OBSERVATIONS_FOR_FEATURES, n - horizon_steps + 1):
            history_slice = observations[:end_idx]
            target_obs = observations[end_idx + horizon_steps - 1]
            dt_horizon = int(target_obs.timestamp - history_slice[-1].timestamp)
            features = cls.extract_features(history_slice, forecast_horizon_seconds=max(1, dt_horizon))
            X.append(features.to_list())
            y.append(target_obs.rps)

        return X, y
