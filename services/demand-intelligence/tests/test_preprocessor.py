"""
SentinelScale — Demand Intelligence — Test: Observation Preprocessor
"""
import pytest
from app.models.demand import DemandObservation
from app.engine.preprocessor import preprocess_observations, compute_statistics
from app.errors import InvalidObservationError


def obs(ts: float, rps: float) -> DemandObservation:
    return DemandObservation(timestamp=ts, rps=rps)


class TestPreprocessObservations:
    def test_empty_input_returns_empty(self):
        result = preprocess_observations([])
        assert result == []

    def test_single_valid_observation_returned(self):
        result = preprocess_observations([obs(1000.0, 100.0)])
        assert len(result) == 1
        assert result[0].rps == 100.0

    def test_out_of_order_sorted_oldest_first(self):
        raw = [obs(1003.0, 30.0), obs(1001.0, 10.0), obs(1002.0, 20.0)]
        result = preprocess_observations(raw)
        timestamps = [o.timestamp for o in result]
        assert timestamps == sorted(timestamps)

    def test_duplicate_timestamps_deduplicated_keep_last(self):
        # Two observations with same timestamp — last (after sort) wins
        raw = [obs(1001.0, 10.0), obs(1001.0, 99.0)]
        result = preprocess_observations(raw)
        assert len(result) == 1
        # After sorting by timestamp both land at index 0; last dict write wins
        assert result[0].rps == 99.0

    def test_negative_rps_raises_explicitly(self):
        # Pydantic prevents constructing DemandObservation with negative RPS via normal init.
        # We use model_construct to bypass validators so we can test the preprocessor's
        # own guard layer independently (defence in depth).
        valid = obs(1001.0, 100.0)
        invalid = DemandObservation.model_construct(timestamp=1002.0, rps=-5.0)
        raw = [valid, invalid]
        with pytest.raises(InvalidObservationError) as exc_info:
            preprocess_observations(raw)
        assert "negative" in str(exc_info.value).lower()

    def test_zero_rps_is_preserved(self):
        raw = [obs(1001.0, 0.0), obs(1002.0, 50.0)]
        result = preprocess_observations(raw)
        assert any(o.rps == 0.0 for o in result)

    def test_large_dataset_sorted(self):
        import random
        random.seed(42)
        raw = [obs(float(i), float(i * 10)) for i in range(1, 101)]
        random.shuffle(raw)
        result = preprocess_observations(raw)
        for i in range(1, len(result)):
            assert result[i].timestamp >= result[i - 1].timestamp


class TestComputeStatistics:
    def test_constant_series_zero_std(self):
        observations = [obs(float(i), 100.0) for i in range(1, 11)]
        mean, std_dev, slope = compute_statistics(observations)
        assert abs(mean - 100.0) < 1e-9
        assert std_dev < 1e-9
        assert abs(slope) < 1e-9

    def test_rising_series_positive_slope(self):
        # Each second RPS increases by 10
        observations = [obs(float(i), float(i * 10)) for i in range(1, 11)]
        _, _, slope = compute_statistics(observations)
        assert slope > 0

    def test_falling_series_negative_slope(self):
        observations = [obs(float(i), float(100 - i * 5)) for i in range(1, 11)]
        _, _, slope = compute_statistics(observations)
        assert slope < 0

    def test_single_observation_zero_slope(self):
        observations = [obs(1000.0, 500.0)]
        mean, std_dev, slope = compute_statistics(observations)
        assert mean == 500.0
        assert slope == 0.0
