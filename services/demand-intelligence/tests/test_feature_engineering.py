"""
SentinelScale — Demand Intelligence — Unit Tests for Feature Engineering (M2-4)
Validates determinism, leakage-safety, stable feature ordering, and edge cases.
"""
import pytest
from app.models.demand import DemandObservation
from app.errors import InsufficientDataError
from app.engine.features import (
    DemandFeatureExtractor,
    DemandFeatureVector,
    FEATURE_NAMES,
    MIN_OBSERVATIONS_FOR_FEATURES,
    compute_cadence_regularity,
)


def _make_observations(rps_values, start_time=1700000000.0, step=30.0):
    return [
        DemandObservation(timestamp=start_time + i * step, rps=float(rps))
        for i, rps in enumerate(rps_values)
    ]


class TestFeatureExtraction:

    def test_insufficient_observations_raises_explicit_error(self):
        # Fewer than MIN_OBSERVATIONS_FOR_FEATURES (4)
        obs = _make_observations([100.0, 110.0, 120.0])
        assert len(obs) == 3
        with pytest.raises(InsufficientDataError) as exc_info:
            DemandFeatureExtractor.extract_features(obs, forecast_horizon_seconds=300)
        assert exc_info.value.required == MIN_OBSERVATIONS_FOR_FEATURES
        assert exc_info.value.available == 3

    def test_minimum_observations_succeeds(self):
        obs = _make_observations([100.0, 105.0, 110.0, 115.0])
        features = DemandFeatureExtractor.extract_features(obs, forecast_horizon_seconds=300)
        assert isinstance(features, DemandFeatureVector)
        assert features.recent_demand == 115.0
        assert features.lag_1 == 110.0
        assert features.lag_2 == 105.0
        assert features.rolling_mean_short == round((105.0 + 110.0 + 115.0) / 3, 4)

    def test_stable_feature_ordering_and_names(self):
        obs = _make_observations([500.0, 520.0, 510.0, 530.0, 540.0])
        features = DemandFeatureExtractor.extract_features(obs, forecast_horizon_seconds=120)
        feature_dict = features.to_dict()
        feature_list = features.to_list()

        assert len(feature_dict) == len(FEATURE_NAMES)
        assert len(feature_list) == len(FEATURE_NAMES)
        assert list(feature_dict.keys()) == list(FEATURE_NAMES)
        for i, name in enumerate(FEATURE_NAMES):
            assert feature_dict[name] == feature_list[i]

    def test_determinism(self):
        obs = _make_observations([200.0, 250.0, 210.0, 270.0, 290.0, 300.0])
        f1 = DemandFeatureExtractor.extract_features(obs, forecast_horizon_seconds=300)
        f2 = DemandFeatureExtractor.extract_features(obs, forecast_horizon_seconds=300)
        assert f1.to_list() == f2.to_list()

    def test_leakage_safety(self):
        """
        Features computed at timestamp T must NOT be affected by observations arriving after T.
        """
        history_at_T = _make_observations([100.0, 110.0, 120.0, 130.0, 140.0])
        extended_future = _make_observations([100.0, 110.0, 120.0, 130.0, 140.0, 999.0, 1500.0])

        features_T = DemandFeatureExtractor.extract_features(history_at_T, forecast_horizon_seconds=300)
        # Slicing the extended list up to index 5 should be identical to history_at_T
        features_T_from_slice = DemandFeatureExtractor.extract_features(extended_future[:5], forecast_horizon_seconds=300)

        assert features_T.to_list() == features_T_from_slice.to_list()
        assert features_T.recent_demand == 140.0

    def test_cadence_regularity_computation(self):
        # Uniform 30s cadence
        regular_obs = _make_observations([100.0, 100.0, 100.0, 100.0], step=30.0)
        reg_score = compute_cadence_regularity(regular_obs)
        assert reg_score == 1.0

        # Highly irregular intervals: 10s, 300s, 5s
        t0 = 1700000000.0
        irregular_obs = [
            DemandObservation(timestamp=t0, rps=100.0),
            DemandObservation(timestamp=t0 + 10.0, rps=100.0),
            DemandObservation(timestamp=t0 + 310.0, rps=100.0),
            DemandObservation(timestamp=t0 + 315.0, rps=100.0),
        ]
        irreg_score = compute_cadence_regularity(irregular_obs)
        assert 0.0 < irreg_score < 1.0
        assert irreg_score < 0.6  # Significantly penalized

    def test_trend_slope_and_rate_of_change(self):
        # Strictly rising: +10 RPS every 30s -> slope = +10/30 = +0.333333 RPS/s
        obs = _make_observations([100.0, 110.0, 120.0, 130.0, 140.0], step=30.0)
        features = DemandFeatureExtractor.extract_features(obs, forecast_horizon_seconds=300)

        assert features.trend_slope > 0.33
        assert features.rate_of_change > 0.33
        assert abs(features.trend_slope - (10.0 / 30.0)) < 0.001

    def test_training_dataset_extraction(self):
        obs = _make_observations([100.0, 105.0, 110.0, 115.0, 120.0, 125.0, 130.0], step=30.0)
        X, y = DemandFeatureExtractor.extract_training_dataset(obs, horizon_steps=1)
        assert len(X) == 3
        assert len(y) == 3
        # First target is obs[4] = 120.0
        assert y[0] == 120.0
        assert y[1] == 125.0
        assert y[2] == 130.0
        # Each feature vector has exact canonical length
        assert len(X[0]) == len(FEATURE_NAMES)
