"""
SentinelScale — Demand Intelligence — Unit Tests for ML Forecaster (M2-5)
Validates model version, bounds, contract compliance, determinism, and fallback.
"""
import json
from pathlib import Path
import jsonschema
import pytest

from app.models.demand import DemandObservation, DemandForecast
from app.errors import InsufficientDataError
from app.engine.ml_forecaster import MLDemandForecaster, ML_MODEL_VERSION, _solve_ridge


@pytest.fixture
def json_schema():
    schema_path = (
        Path(__file__).parent.parent.parent.parent
        / "contracts"
        / "demand"
        / "demand_forecast.schema.json"
    )
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _make_observations(rps_values, start_time=1700000000.0, step=30.0):
    return [
        DemandObservation(timestamp=start_time + i * step, rps=float(rps))
        for i, rps in enumerate(rps_values)
    ]


class TestMLForecaster:

    def test_solve_ridge_basic(self):
        # y = 2*x + 1
        X = [[1.0], [2.0], [3.0], [4.0]]
        y = [3.0, 5.0, 7.0, 9.0]
        weights, intercept = _solve_ridge(X, y, alpha=0.01)
        assert len(weights) == 1
        assert abs(weights[0] - 2.0) < 0.1
        assert abs(intercept - 1.0) < 0.3

    def test_insufficient_data_raises_explicit_error(self):
        # Fewer than 2 observations -> InsufficientDataError
        forecaster = MLDemandForecaster()
        with pytest.raises(InsufficientDataError) as exc_info:
            forecaster.predict([DemandObservation(timestamp=1700000000.0, rps=100.0)], 300)
        assert exc_info.value.required == 2

    def test_sparse_data_falls_back_to_baseline(self):
        # 3 observations: >= 2 (sufficient for baseline) but < 4 (insufficient for full ML)
        obs = _make_observations([100.0, 110.0, 120.0])
        forecaster = MLDemandForecaster()
        forecast = forecaster.predict(obs, forecast_horizon_seconds=300)

        assert isinstance(forecast, DemandForecast)
        # Should gracefully fall back to baseline model version "demand-v1"
        assert forecast.model_version == "demand-v1"
        assert forecast.predicted_legitimate_rps > 0.0

    def test_ml_prediction_with_sufficient_data(self, json_schema):
        # 10 observations: sufficient for full ML Ridge modeling
        obs = _make_observations([100.0, 102.0, 105.0, 108.0, 110.0, 112.0, 115.0, 118.0, 120.0, 122.0])
        forecaster = MLDemandForecaster(ridge_alpha=1.0)
        forecast = forecaster.predict(obs, forecast_horizon_seconds=120, trace_id="trace-ml-test-123")

        assert forecast.model_version == ML_MODEL_VERSION
        assert forecast.trace_id == "trace-ml-test-123"
        assert forecast.forecast_horizon_seconds == 120
        assert forecast.predicted_legitimate_rps >= 0.0
        assert forecast.lower_bound_rps <= forecast.predicted_legitimate_rps <= forecast.upper_bound_rps
        assert 0.0 <= forecast.confidence <= 1.0

        # Contract schema conformance
        jsonschema.validate(instance=forecast.model_dump(), schema=json_schema)

    def test_determinism(self):
        obs = _make_observations([800.0, 850.0, 820.0, 860.0, 840.0, 870.0, 860.0, 890.0])
        forecaster = MLDemandForecaster(ridge_alpha=0.5)
        f1 = forecaster.predict(obs, forecast_horizon_seconds=300)
        f2 = forecaster.predict(obs, forecast_horizon_seconds=300)

        assert f1.predicted_legitimate_rps == f2.predicted_legitimate_rps
        assert f1.lower_bound_rps == f2.lower_bound_rps
        assert f1.upper_bound_rps == f2.upper_bound_rps
        assert f1.confidence == f2.confidence

    def test_falling_demand_non_negative(self):
        # Steeply dropping demand: ensure prediction never goes negative
        obs = _make_observations([500.0, 400.0, 300.0, 200.0, 100.0, 50.0, 20.0, 10.0])
        forecaster = MLDemandForecaster()
        forecast = forecaster.predict(obs, forecast_horizon_seconds=600)

        assert forecast.predicted_legitimate_rps >= 0.0
        assert forecast.lower_bound_rps >= 0.0
        assert forecast.lower_bound_rps <= forecast.predicted_legitimate_rps <= forecast.upper_bound_rps
