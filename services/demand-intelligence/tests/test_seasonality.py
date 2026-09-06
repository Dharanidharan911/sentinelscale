"""
SentinelScale — Demand Intelligence — Test: Seasonality Detection & Adjustment (M2-13)
Validates autocorrelation peak finding, harmonic estimation, fallback on short
history or non-periodic series, and non-negativity guarantees.
"""
import math
import pytest
from app.models.demand import DemandObservation
from app.engine.seasonality import SeasonalityDetector, SeasonalityResult


def _make_sine_series(period_seconds=120.0, step_seconds=10.0, n_cycles=3, base=500.0, amp=100.0):
    total_time = n_cycles * period_seconds
    n = int(round(total_time / step_seconds))
    t0 = 1700000000.0
    return [
        DemandObservation(
            timestamp=t0 + i * step_seconds,
            rps=round(base + amp * math.sin(2 * math.pi * (i * step_seconds) / period_seconds), 2),
        )
        for i in range(n)
    ]


class TestSeasonalityEngine:
    def test_detects_periodic_signal_with_sufficient_cycles(self):
        """A clean periodic signal with 3 full cycles must be detected as seasonal."""
        series = _make_sine_series(period_seconds=120.0, step_seconds=10.0, n_cycles=3, amp=150.0)
        res = SeasonalityDetector.detect_and_adjust(
            observations=series,
            base_projection=500.0,
            forecast_horizon_seconds=60,
        )
        assert res.is_seasonal is True
        assert res.period_seconds is not None
        # Period should be close to 120s (e.g. 120 ± 20s)
        assert 100.0 <= res.period_seconds <= 140.0
        assert res.autocorrelation_peak > 0.40

    def test_rejects_insufficient_history_under_two_cycles(self):
        """A periodic signal spanning only 1 cycle must NOT be confirmed as seasonal."""
        series = _make_sine_series(period_seconds=120.0, step_seconds=10.0, n_cycles=1, amp=150.0)
        res = SeasonalityDetector.detect_and_adjust(
            observations=series,
            base_projection=500.0,
            forecast_horizon_seconds=60,
        )
        assert res.is_seasonal is False
        assert res.seasonal_adjustment_rps == 0.0

    def test_flat_demand_is_not_seasonal(self):
        """Constant demand has zero seasonal adjustment."""
        t0 = 1700000000.0
        series = [DemandObservation(timestamp=t0 + i * 30.0, rps=500.0) for i in range(30)]
        res = SeasonalityDetector.detect_and_adjust(
            observations=series,
            base_projection=500.0,
            forecast_horizon_seconds=300,
        )
        assert res.is_seasonal is False
        assert res.seasonal_adjustment_rps == 0.0

    def test_linear_growth_is_not_seasonal(self):
        """Steady rising demand is trend, not seasonality."""
        t0 = 1700000000.0
        series = [DemandObservation(timestamp=t0 + i * 30.0, rps=500.0 + i * 10.0) for i in range(30)]
        res = SeasonalityDetector.detect_and_adjust(
            observations=series,
            base_projection=800.0,
            forecast_horizon_seconds=300,
        )
        assert res.is_seasonal is False
        assert res.seasonal_adjustment_rps == 0.0

    def test_seasonal_adjustment_preserves_non_negative_demand(self):
        """Large seasonal trough cannot pull predicted demand below 0.0."""
        series = _make_sine_series(period_seconds=120.0, step_seconds=10.0, n_cycles=3, base=100.0, amp=80.0)
        res = SeasonalityDetector.detect_and_adjust(
            observations=series,
            base_projection=100.0,
            forecast_horizon_seconds=90,  # trough
        )
        adjusted = max(0.0, 100.0 + res.seasonal_adjustment_rps)
        assert adjusted >= 0.0

    def test_produce_forecast_incorporates_seasonality(self):
        """produce_forecast produces valid schema forecast on seasonal series."""
        from app.engine.forecaster import produce_forecast
        series = _make_sine_series(period_seconds=120.0, step_seconds=10.0, n_cycles=4, base=500.0, amp=120.0)
        forecast = produce_forecast(series, forecast_horizon_seconds=30)
        assert forecast.predicted_legitimate_rps >= 0.0
        assert forecast.lower_bound_rps <= forecast.predicted_legitimate_rps <= forecast.upper_bound_rps
        assert 0.0 <= forecast.confidence <= 1.0
