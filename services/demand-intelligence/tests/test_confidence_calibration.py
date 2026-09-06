"""
SentinelScale — Demand Intelligence — Test: Confidence Calibration (M2-10)
Empirically verifies calibration properties of the forecast confidence score:
- Monotonic degradation across sample scarcity, high variance, horizon distance,
  cadence irregularity, and data quality staleness.
- Strict bounded range [0.0, 1.0].
- Determinism.
"""
import pytest
from app.models.demand import DemandObservation
from app.engine.forecaster import produce_forecast, _compute_confidence


def _obs(ts: float, rps: float) -> DemandObservation:
    return DemandObservation(timestamp=ts, rps=rps)


def _make_series(n: int, rps_func, step: float = 30.0, start_time: float = 1700000000.0):
    return [_obs(start_time + i * step, rps_func(i)) for i in range(n)]


class TestConfidenceCalibration:

    def test_confidence_strictly_bounded(self):
        """Confidence score must always fall in [0.0, 1.0]."""
        for n in [2, 5, 20, 100]:
            for cv in [0.0, 0.1, 0.5, 2.0]:
                for h in [10, 300, 3600, 86400]:
                    conf = _compute_confidence(
                        n_samples=n,
                        mean_rps=500.0,
                        std_dev_rps=500.0 * cv,
                        time_span=n * 30.0,
                        horizon=h,
                        sampling_regularity=1.0,
                        data_quality_score=1.0,
                    )
                    assert 0.0 <= conf <= 1.0

    def test_monotonic_sample_scarcity_penalty(self):
        """Fewer observations must yield monotonically lower confidence."""
        c_large = produce_forecast(_make_series(50, lambda i: 500.0), 300).confidence
        c_med = produce_forecast(_make_series(15, lambda i: 500.0), 300).confidence
        c_sparse = produce_forecast(_make_series(3, lambda i: 500.0), 300).confidence

        assert c_large > c_med > c_sparse

    def test_monotonic_variance_penalty(self):
        """Higher relative variance (CV) must yield monotonically lower confidence."""
        c_low_var = produce_forecast(_make_series(25, lambda i: 500.0 + (i % 2) * 5.0), 300).confidence
        c_med_var = produce_forecast(_make_series(25, lambda i: 500.0 + (i % 2) * 50.0), 300).confidence
        c_high_var = produce_forecast(_make_series(25, lambda i: 500.0 + (i % 2) * 300.0), 300).confidence

        assert c_low_var > c_med_var > c_high_var

    def test_monotonic_horizon_penalty(self):
        """Forecasting well beyond the historical time span must degrade confidence."""
        series = _make_series(20, lambda i: 500.0)  # time span = 570s
        c_within_window = produce_forecast(series, 300).confidence
        c_beyond_window = produce_forecast(series, 1800).confidence
        c_far_beyond_window = produce_forecast(series, 7200).confidence

        assert c_within_window > c_beyond_window > c_far_beyond_window

    def test_cadence_irregularity_penalty(self):
        """Irregular sampling cadence degrades confidence."""
        reg_series = _make_series(10, lambda i: 500.0, step=30.0)
        irreg_series = [
            _obs(1700000000.0, 500.0),
            _obs(1700000005.0, 500.0),
            _obs(1700000200.0, 500.0),
            _obs(1700000205.0, 500.0),
            _obs(1700000600.0, 500.0),
            _obs(1700000605.0, 500.0),
            _obs(1700001200.0, 500.0),
            _obs(1700001205.0, 500.0),
            _obs(1700002000.0, 500.0),
            _obs(1700002005.0, 500.0),
        ]
        c_reg = produce_forecast(reg_series, 300).confidence
        c_irreg = produce_forecast(irreg_series, 300).confidence

        assert c_reg > c_irreg
