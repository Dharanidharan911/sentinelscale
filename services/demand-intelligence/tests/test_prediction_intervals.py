"""
SentinelScale — Demand Intelligence — Test: Prediction Intervals (M2-9)
Validates mathematical properties, bounds, horizon scaling, and cadence dilation
of prediction intervals.
"""
import pytest
from app.models.demand import DemandObservation
from app.engine.forecaster import compute_prediction_interval, produce_forecast
from app.engine.ml_forecaster import MLDemandForecaster


def _make_series(n=20, base_rps=500.0, step=30.0, std_jitter=10.0):
    import math
    return [
        DemandObservation(
            timestamp=1700000000.0 + i * step,
            rps=base_rps + std_jitter * math.sin(i),
        )
        for i in range(n)
    ]


class TestPredictionIntervalProperties:
    def test_bounds_invariant_always_holds(self):
        """Invariant: 0.0 <= lower <= predicted <= upper across various inputs."""
        for horizon in [10, 60, 300, 1800, 7200]:
            lower, upper = compute_prediction_interval(
                predicted=100.0,
                std_dev_rps=20.0,
                time_span=300.0,
                forecast_horizon_seconds=horizon,
                sampling_regularity=1.0,
            )
            assert 0.0 <= lower <= 100.0 <= upper

    def test_interval_widens_monotonically_with_horizon(self):
        """Uncertainty must increase as the forecast horizon extends."""
        widths = []
        horizons = [30, 120, 300, 900, 3600]
        for h in horizons:
            lower, upper = compute_prediction_interval(
                predicted=250.0,
                std_dev_rps=15.0,
                time_span=300.0,
                forecast_horizon_seconds=h,
                sampling_regularity=1.0,
            )
            widths.append(upper - lower)

        for i in range(len(widths) - 1):
            assert widths[i] < widths[i + 1], f"Width at {horizons[i]}s ({widths[i]}) should be < width at {horizons[i+1]}s ({widths[i+1]})"

    def test_irregular_cadence_dilates_interval(self):
        """Irregular sampling cadence must produce wider prediction interval than regular."""
        lower_reg, upper_reg = compute_prediction_interval(
            predicted=300.0,
            std_dev_rps=20.0,
            time_span=300.0,
            forecast_horizon_seconds=300,
            sampling_regularity=1.0,
        )
        lower_irreg, upper_irreg = compute_prediction_interval(
            predicted=300.0,
            std_dev_rps=20.0,
            time_span=300.0,
            forecast_horizon_seconds=300,
            sampling_regularity=0.3,
        )
        width_reg = upper_reg - lower_reg
        width_irreg = upper_irreg - lower_irreg
        assert width_irreg > width_reg

    def test_zero_variance_constant_series(self):
        """When historical variance is zero, lower bound does not violate 0 <= lower <= predicted."""
        lower, upper = compute_prediction_interval(
            predicted=500.0,
            std_dev_rps=0.0,
            time_span=300.0,
            forecast_horizon_seconds=300,
        )
        assert lower == 500.0
        assert upper == 500.0

    def test_zero_predicted_demand_clamps_lower_bound_to_zero(self):
        """Zero demand lower bound cannot go below zero."""
        lower, upper = compute_prediction_interval(
            predicted=0.0,
            std_dev_rps=5.0,
            time_span=300.0,
            forecast_horizon_seconds=300,
        )
        assert lower == 0.0
        assert upper >= 0.0

    def test_ml_forecaster_honors_prediction_intervals(self):
        """ML model must also produce bounded, valid intervals expanding with horizon."""
        series = _make_series(n=20, base_rps=400.0)
        ml = MLDemandForecaster()
        fc_short = ml.predict(series, forecast_horizon_seconds=60)
        fc_long = ml.predict(series, forecast_horizon_seconds=1800)

        assert 0.0 <= fc_short.lower_bound_rps <= fc_short.predicted_legitimate_rps <= fc_short.upper_bound_rps
        assert 0.0 <= fc_long.lower_bound_rps <= fc_long.predicted_legitimate_rps <= fc_long.upper_bound_rps
        width_short = fc_short.upper_bound_rps - fc_short.lower_bound_rps
        width_long = fc_long.upper_bound_rps - fc_long.lower_bound_rps
        assert width_long > width_short
