"""
SentinelScale — Demand Intelligence — ML Forecasting Candidate (M2-5)
Candidate Model: Ridge Regularized Linear Forecaster (demand-ml-v1)

Design principles:
1. Deterministic & Reproducible: Closed-form regularized linear algebra (no stochastic gradient noise).
2. Lightweight: Pure mathematical execution without heavy external C/CUDA runtimes.
3. Feature-Engineered: Uses the canonical 12-feature DemandFeatureVector.
4. Failure-Safe: Falls back explicitly and transparently to baseline RWMA (demand-v1)
   if historical samples are insufficient or if numerical instability occurs.
5. Invariant Bounds: Predicted RPS >= 0.0; lower_bound <= predicted <= upper_bound.
6. Frozen Contract: Returns canonical DemandForecast v1.0.0.
"""
import math
import uuid
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.models.demand import DemandForecast, DemandObservation
from app.engine.preprocessor import preprocess_observations, compute_statistics
from app.engine.data_quality import DataQualityAssessor
from app.engine.features import (
    DemandFeatureExtractor,
    DemandFeatureVector,
    MIN_OBSERVATIONS_FOR_FEATURES,
    compute_cadence_regularity,
)
from app.engine.forecaster import produce_forecast, _compute_confidence, compute_prediction_interval
from app.errors import InsufficientDataError, ForecastCalculationError
from app.config.settings import settings
from app.logging import logger

ML_MODEL_VERSION = "demand-ml-v1"
MIN_OBSERVATIONS_FOR_ML = 4
MIN_SAMPLES_FOR_ONLINE_FIT = 8


def _solve_ridge(
    X: List[List[float]],
    y: List[float],
    alpha: float = 1.0,
) -> Tuple[List[float], float]:
    """
    Solve closed-form Ridge Regression (w, intercept) using standard linear algebra:
        w = (X_c^T X_c + alpha * I)^(-1) X_c^T y_c
    Pure-Python / math implementation to avoid heavy dependency requirements.
    """
    n = len(X)
    p = len(X[0])

    # Means for centering
    x_mean = [sum(X[i][j] for i in range(n)) / n for j in range(p)]
    y_mean = sum(y) / n

    # Centered data
    X_c = [[X[i][j] - x_mean[j] for j in range(p)] for i in range(n)]
    y_c = [y[i] - y_mean for i in range(n)]

    # Compute A = X_c^T X_c + alpha * I (p x p matrix)
    A = [[0.0] * p for _ in range(p)]
    for j1 in range(p):
        for j2 in range(p):
            dot = sum(X_c[i][j1] * X_c[i][j2] for i in range(n))
            if j1 == j2:
                dot += alpha
            A[j1][j2] = dot

    # Compute b = X_c^T y_c (p x 1 vector)
    b = [sum(X_c[i][j] * y_c[i] for i in range(n)) for j in range(p)]

    # Solve A w = b via Gaussian elimination with partial pivoting
    # Augmented matrix [A | b]
    M = [A[i][:] + [b[i]] for i in range(p)]

    for col in range(p):
        # Pivot selection
        max_row = max(range(col, p), key=lambda r: abs(M[r][col]))
        if abs(M[max_row][col]) < 1e-12:
            # Degenerate / singular column -> zero weight fallback
            continue
        M[col], M[max_row] = M[max_row], M[col]

        pivot = M[col][col]
        for c in range(col, p + 1):
            M[col][c] /= pivot

        for r in range(p):
            if r != col:
                factor = M[r][col]
                for c in range(col, p + 1):
                    M[r][c] -= factor * M[col][c]

    weights = [M[i][p] for i in range(p)]
    intercept = y_mean - sum(weights[j] * x_mean[j] for j in range(p))
    return weights, intercept


class MLDemandForecaster:
    """
    Deterministic Feature-Engineered ML Demand Forecaster.
    Uses Ridge regularized linear modeling with local adaptation.
    """

    def __init__(self, ridge_alpha: float = 1.0):
        self.ridge_alpha = max(0.01, float(ridge_alpha))

    def predict(
        self,
        observations: List[DemandObservation],
        forecast_horizon_seconds: int,
        trace_id: Optional[str] = None,
    ) -> DemandForecast:
        """
        Produce a DemandForecast using the ML candidate model (demand-ml-v1).

        Args:
            observations: Raw (unsorted, potentially invalid) observation list.
            forecast_horizon_seconds: Future projection horizon.
            trace_id: Trace correlation ID.

        Returns:
            DemandForecast object conforming to contracts/demand/demand_forecast.schema.json v1.0.0.
        """
        # Step 1: Preprocessing & Basic Validation
        cleaned = preprocess_observations(observations)
        n = len(cleaned)

        if n < settings.FORECAST_MIN_OBSERVATIONS:
            raise InsufficientDataError(
                required=settings.FORECAST_MIN_OBSERVATIONS,
                available=n,
            )

        # Step 2: Fallback check — if observations are fewer than MIN_OBSERVATIONS_FOR_ML (4),
        # gracefully fall back to baseline RWMA engine.
        if n < MIN_OBSERVATIONS_FOR_ML:
            logger.info(
                "ML forecaster falling back to baseline: insufficient observations for feature extraction",
                extra={
                    "available_samples": n,
                    "required_for_ml": MIN_OBSERVATIONS_FOR_ML,
                    "model_version": ML_MODEL_VERSION,
                    "fallback_to": settings.MODEL_VERSION,
                },
            )
            return produce_forecast(cleaned, forecast_horizon_seconds, trace_id=trace_id)

        try:
            # Step 3: Feature Extraction
            features = DemandFeatureExtractor.extract_features(
                cleaned, forecast_horizon_seconds=forecast_horizon_seconds
            )
            time_span = cleaned[-1].timestamp - cleaned[0].timestamp
            mean_rps, std_dev_rps, trend_slope = compute_statistics(cleaned)

            # Step 4: Ridge Model Prediction
            # If we have enough history to construct a local training set (n >= 8),
            # fit Ridge weights on local historical transitions.
            if n >= MIN_SAMPLES_FOR_ONLINE_FIT:
                step_interval = max(1, int(time_span / (n - 1)))
                horizon_steps = max(1, int(round(forecast_horizon_seconds / step_interval)))
                horizon_steps = min(horizon_steps, max(1, n // 3))

                X_train, y_train = DemandFeatureExtractor.extract_training_dataset(
                    cleaned, horizon_steps=horizon_steps
                )

                if len(X_train) >= 4:
                    weights, intercept = _solve_ridge(X_train, y_train, alpha=self.ridge_alpha)
                    current_x = features.to_list()
                    raw_prediction = intercept + sum(w * x for w, x in zip(weights, current_x))
                else:
                    raw_prediction = self._heuristic_ridge_projection(features, forecast_horizon_seconds)
            else:
                raw_prediction = self._heuristic_ridge_projection(features, forecast_horizon_seconds)

            # Step 5: Sanity and Boundary Clamping
            val = float(raw_prediction)
            if not math.isfinite(val):
                # Fallback on numerical anomaly
                return produce_forecast(cleaned, forecast_horizon_seconds, trace_id=trace_id)
            predicted = max(0.0, val)

            # Step 6: Prediction Intervals with horizon and regularity dilation (M2-9)
            regularity = compute_cadence_regularity(cleaned)
            lower, upper = compute_prediction_interval(
                predicted=predicted,
                std_dev_rps=max(std_dev_rps, 1.0),
                time_span=time_span,
                forecast_horizon_seconds=forecast_horizon_seconds,
                sampling_regularity=regularity,
            )

            # Step 7: Confidence Estimation with Data Quality Calibration (M2-10, M2-12)
            quality_report = DataQualityAssessor.assess(cleaned)
            confidence = _compute_confidence(
                n_samples=n,
                mean_rps=mean_rps,
                std_dev_rps=std_dev_rps,
                time_span=time_span,
                horizon=forecast_horizon_seconds,
                sampling_regularity=regularity,
                data_quality_score=quality_report.quality_score,
            )

            # Step 8: Build Frozen Contract
            effective_trace_id = trace_id or f"trace-{uuid.uuid4().hex[:16]}"
            now_iso = datetime.now(timezone.utc).isoformat()

            return DemandForecast(
                event_id=str(uuid.uuid4()),
                trace_id=effective_trace_id,
                generated_at=now_iso,
                contract_version=settings.CONTRACT_VERSION,
                service_version=settings.SERVICE_VERSION,
                model_version=ML_MODEL_VERSION,
                forecast_horizon_seconds=forecast_horizon_seconds,
                predicted_legitimate_rps=round(predicted, 4),
                lower_bound_rps=round(lower, 4),
                upper_bound_rps=round(upper, 4),
                confidence=confidence,
            )

        except Exception as exc:
            logger.warning(
                f"ML forecasting calculation failed ({exc}); falling back to baseline",
                extra={"trace_id": trace_id, "error": str(exc)},
            )
            # Failure safety invariant: never crash if baseline is available
            return produce_forecast(cleaned, forecast_horizon_seconds, trace_id=trace_id)

    @staticmethod
    def _heuristic_ridge_projection(
        features: DemandFeatureVector,
        forecast_horizon_seconds: int,
    ) -> float:
        """
        Regularized prior projection when sample count is sufficient for feature
        extraction (4 <= n < 8) but insufficient for multi-sample regression training.
        Combines recent demand, short rolling mean, and damped trend.
        """
        w_recent = 0.50
        w_rolling = 0.35
        w_lag = 0.15

        base = (
            w_recent * features.recent_demand
            + w_rolling * features.rolling_mean_short
            + w_lag * features.lag_1
        )
        # Apply damped trend
        damped_slope = max(-5.0, min(5.0, features.trend_slope * 0.8))
        projected = base + damped_slope * forecast_horizon_seconds
        return max(0.0, projected)
