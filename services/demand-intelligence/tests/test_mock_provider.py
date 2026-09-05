"""
SentinelScale — Demand Intelligence — Test: Mock Provider
"""
import pytest
from app.providers.mock_provider import MockDemandProvider


class TestMockDemandProvider:
    REFERENCE_TIME = 1_700_000_000.0

    def setup_method(self):
        self.provider = MockDemandProvider(reference_time=self.REFERENCE_TIME)

    def test_provider_name(self):
        assert self.provider.name == "MockDemandProvider"

    def test_returns_observations(self):
        obs = self.provider.get_observations(window_seconds=3600)
        assert len(obs) > 0

    def test_observations_time_ordered(self):
        obs = self.provider.get_observations(window_seconds=3600)
        timestamps = [o.timestamp for o in obs]
        assert timestamps == sorted(timestamps)

    def test_all_rps_non_negative(self):
        obs = self.provider.get_observations(window_seconds=3600)
        for o in obs:
            assert o.rps >= 0.0

    def test_shorter_window_fewer_observations(self):
        obs_long = self.provider.get_observations(window_seconds=3600)
        obs_short = self.provider.get_observations(window_seconds=300)
        assert len(obs_short) <= len(obs_long)

    def test_deterministic_with_same_reference_time(self):
        p1 = MockDemandProvider(reference_time=self.REFERENCE_TIME)
        p2 = MockDemandProvider(reference_time=self.REFERENCE_TIME)
        obs1 = p1.get_observations(window_seconds=600)
        obs2 = p2.get_observations(window_seconds=600)
        assert len(obs1) == len(obs2)
        for o1, o2 in zip(obs1, obs2):
            assert o1.timestamp == o2.timestamp
            assert o1.rps == o2.rps

    def test_minimum_window_returns_at_least_one_observation(self):
        obs = self.provider.get_observations(window_seconds=60)
        assert len(obs) >= 1
