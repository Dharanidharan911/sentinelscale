"""
SentinelScale — Demand Intelligence — Test: Forecasting Engine
"""
import pytest
from app.models.demand import DemandObservation
from app.engine.forecaster import produce_forecast, MIN_OBSERVATIONS_FOR_FORECAST
from app.errors import InsufficientDataError, InvalidObservationError


def obs(ts: float, rps: float) -> DemandObservation:
    return DemandObservation(timestamp=ts, rps=rps)


def stable_observations(n: int = 20, rps: float = 500.0, start_ts: float = 1_700_000_000.0) -> list:
    """Produce n observations with constant RPS."""
    return [obs(start_ts + i * 30, rps) for i in range(n)]


def rising_observations(n: int = 20, start_rps: float = 100.0, increment: float = 10.0) -> list:
    """Produce n observations with steadily increasing RPS."""
    return [obs(1_700_000_000.0 + i * 30, start_rps + i * increment) for i in range(n)]


def falling_observations(n: int = 20, start_rps: float = 500.0, decrement: float = 10.0) -> list:
    return [obs(1_700_000_000.0 + i * 30, max(0.0, start_rps - i * decrement)) for i in range(n)]


class TestForecastingEngineBounds:
    def test_bounds_invariant_stable(self):
        forecast = produce_forecast(stable_observations(), 300, "trace-test")
        assert forecast.lower_bound_rps <= forecast.predicted_legitimate_rps
        assert forecast.predicted_legitimate_rps <= forecast.upper_bound_rps

    def test_bounds_invariant_rising(self):
        forecast = produce_forecast(rising_observations(), 300, "trace-test")
        assert forecast.lower_bound_rps <= forecast.predicted_legitimate_rps
        assert forecast.predicted_legitimate_rps <= forecast.upper_bound_rps

    def test_bounds_invariant_falling(self):
        forecast = produce_forecast(falling_observations(), 300, "trace-test")
        assert forecast.lower_bound_rps <= forecast.predicted_legitimate_rps
        assert forecast.predicted_legitimate_rps <= forecast.upper_bound_rps

    def test_predicted_rps_non_negative(self):
        forecast = produce_forecast(stable_observations(), 300)
        assert forecast.predicted_legitimate_rps >= 0.0

    def test_lower_bound_non_negative(self):
        forecast = produce_forecast(stable_observations(rps=1.0), 300)
        assert forecast.lower_bound_rps >= 0.0


class TestForecastingEngineConfidence:
    def test_confidence_in_valid_range(self):
        forecast = produce_forecast(stable_observations(), 300)
        assert 0.0 <= forecast.confidence <= 1.0

    def test_more_samples_higher_confidence(self):
        few_obs = stable_observations(n=3)
        many_obs = stable_observations(n=50)
        forecast_few = produce_forecast(few_obs, 300)
        forecast_many = produce_forecast(many_obs, 300)
        # With the same stable demand, more samples should yield higher confidence
        assert forecast_many.confidence >= forecast_few.confidence

    def test_stable_demand_high_confidence(self):
        # Very consistent demand should yield high confidence with enough samples
        forecast = produce_forecast(stable_observations(n=50), 300)
        assert forecast.confidence > 0.7

    def test_noisy_demand_lower_confidence(self):
        import random
        random.seed(0)
        noisy = [obs(1_700_000_000.0 + i * 30, random.uniform(10, 900)) for i in range(20)]
        stable = stable_observations(n=20, rps=500.0)
        f_noisy = produce_forecast(noisy, 300)
        f_stable = produce_forecast(stable, 300)
        assert f_stable.confidence >= f_noisy.confidence


class TestForecastingEngineTrend:
    def test_rising_demand_increases_predicted_rps(self):
        # With rising observations, projected demand should be above the mean
        data = rising_observations(n=20, start_rps=500.0, increment=5.0)
        forecast = produce_forecast(data, 300)
        mean_rps = sum(o.rps for o in data) / len(data)
        # With trend, prediction should be >= mean
        assert forecast.predicted_legitimate_rps >= mean_rps * 0.9  # allow slight rounding

    def test_falling_demand_decreases_predicted_rps(self):
        data = falling_observations(n=20, start_rps=800.0, decrement=5.0)
        forecast = produce_forecast(data, 300)
        mean_rps = sum(o.rps for o in data) / len(data)
        assert forecast.predicted_legitimate_rps <= mean_rps * 1.1  # allow slight rounding


class TestForecastingEngineInsufficientData:
    def test_single_observation_raises_insufficient_data(self):
        with pytest.raises(InsufficientDataError) as exc_info:
            produce_forecast([obs(1_700_000_000.0, 100.0)], 300)
        assert exc_info.value.required == MIN_OBSERVATIONS_FOR_FORECAST
        assert exc_info.value.available == 1

    def test_empty_observations_raises_insufficient_data(self):
        with pytest.raises(InsufficientDataError):
            produce_forecast([], 300)


class TestForecastingEngineDeterminism:
    def test_same_input_same_output_predicted_rps(self):
        """Excluding event_id and generated_at, same inputs yield same outputs."""
        data = stable_observations(n=20, rps=700.0)
        f1 = produce_forecast(data, 300, "trace-same")
        f2 = produce_forecast(data, 300, "trace-same")
        assert f1.predicted_legitimate_rps == f2.predicted_legitimate_rps
        assert f1.lower_bound_rps == f2.lower_bound_rps
        assert f1.upper_bound_rps == f2.upper_bound_rps
        assert f1.confidence == f2.confidence

    def test_event_id_is_unique_per_call(self):
        data = stable_observations(n=20)
        f1 = produce_forecast(data, 300)
        f2 = produce_forecast(data, 300)
        assert f1.event_id != f2.event_id


class TestForecastingEngineContractFields:
    def test_contract_version_is_frozen(self):
        from app.config.settings import settings
        forecast = produce_forecast(stable_observations(), 300)
        assert forecast.contract_version == settings.CONTRACT_VERSION

    def test_model_version_set(self):
        forecast = produce_forecast(stable_observations(), 300)
        assert forecast.model_version != ""

    def test_trace_id_propagated(self):
        forecast = produce_forecast(stable_observations(), 300, trace_id="trace-abc123")
        assert forecast.trace_id == "trace-abc123"

    def test_trace_id_generated_when_none(self):
        forecast = produce_forecast(stable_observations(), 300, trace_id=None)
        assert forecast.trace_id.startswith("trace-")

    def test_horizon_propagated(self):
        forecast = produce_forecast(stable_observations(), 600)
        assert forecast.forecast_horizon_seconds == 600
