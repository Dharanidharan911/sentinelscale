"""
SentinelScale — Demand Intelligence — Test: DemandObservation domain model
"""
import pytest
from pydantic import ValidationError
from app.models.demand import DemandObservation, ForecastRequest


class TestDemandObservationModel:
    def test_valid_observation(self):
        obs = DemandObservation(timestamp=1700000000.0, rps=500.0)
        assert obs.rps == 500.0
        assert obs.timestamp == 1700000000.0

    def test_zero_rps_is_valid(self):
        obs = DemandObservation(timestamp=1700000000.0, rps=0.0)
        assert obs.rps == 0.0

    def test_negative_rps_rejected(self):
        with pytest.raises(ValidationError):
            DemandObservation(timestamp=1700000000.0, rps=-1.0)

    def test_negative_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            DemandObservation(timestamp=-100.0, rps=100.0)

    def test_zero_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            DemandObservation(timestamp=0.0, rps=100.0)

    def test_large_rps_is_valid(self):
        obs = DemandObservation(timestamp=1700000000.0, rps=999999.99)
        assert obs.rps == 999999.99


class TestForecastRequestModel:
    def test_default_request(self):
        req = ForecastRequest()
        assert req.forecast_horizon_seconds == 300
        assert req.target_service == "demo-api"
        assert req.trace_id is None
        assert req.observations is None

    def test_custom_horizon(self):
        req = ForecastRequest(forecast_horizon_seconds=900)
        assert req.forecast_horizon_seconds == 900

    def test_zero_horizon_rejected(self):
        with pytest.raises(ValidationError):
            ForecastRequest(forecast_horizon_seconds=0)

    def test_inline_observations_accepted(self):
        obs = [DemandObservation(timestamp=1700000000.0, rps=100.0)]
        req = ForecastRequest(observations=obs)
        assert len(req.observations) == 1
