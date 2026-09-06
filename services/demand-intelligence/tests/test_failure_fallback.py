"""
SentinelScale — Demand Intelligence — Test: Failure & Fallback Handling (M2-11)
Validates explicit error propagation, non-zero failure semantics, provider failure
HTTP 503 mapping, and transparent ML-to-baseline fallback upon numerical anomalies.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.models.demand import DemandObservation, DemandForecast
from app.providers.base import DemandProvider
from app.errors import (
    InsufficientDataError,
    InvalidObservationError,
    ProviderUnavailableError,
)
from app.engine.ml_forecaster import MLDemandForecaster
from app.services.forecaster import DemandForecastingService

client = TestClient(app)


def _make_obs(n=10, rps=100.0):
    return [DemandObservation(timestamp=1700000000.0 + i * 30.0, rps=rps) for i in range(n)]


class TestFailureSemantics:

    def test_insufficient_data_returns_422_with_details(self):
        """Fewer than 2 observations returns 422 and never zero demand."""
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": [{"timestamp": 1700000000.0, "rps": 50.0}],
        }
        resp = client.post("/api/v1/demand/forecast", json=payload)
        assert resp.status_code == 422
        data = resp.json()["detail"]
        assert data["error"] == "insufficient_data"
        assert data["required_samples"] == 2
        assert data["available_samples"] == 1

    def test_invalid_negative_rps_rejected_at_validation(self):
        """Negative demand is physically invalid and must return 422."""
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": [
                {"timestamp": 1700000000.0, "rps": -10.0},
                {"timestamp": 1700000030.0, "rps": 10.0},
            ],
        }
        resp = client.post("/api/v1/demand/forecast", json=payload)
        assert resp.status_code == 422

    def test_provider_unavailable_returns_503(self):
        """When an upstream telemetry provider fails, service returns 503, never zero demand."""
        class FailingProvider(DemandProvider):
            @property
            def name(self) -> str:
                return "failing-test-provider"

            def get_observations(self, window_seconds: int):
                raise ProviderUnavailableError("failing-test-provider", "Connection timeout to Prometheus")

        service = DemandForecastingService(default_provider=FailingProvider())
        from app.api.v1.endpoints import get_forecaster_service
        app.dependency_overrides[get_forecaster_service] = lambda: service
        try:
            resp = client.post("/api/v1/demand/forecast", json={"forecast_horizon_seconds": 300})
            assert resp.status_code == 503
            detail = resp.json()["detail"]
            assert detail["error"] == "provider_unavailable"
            assert detail["provider"] == "failing-test-provider"
            assert "Connection timeout" in detail["message"]
        finally:
            app.dependency_overrides.clear()

    def test_ml_singular_matrix_falls_back_to_baseline(self):
        """
        If the ML candidate encounters a numerical anomaly during Ridge fit,
        it must fallback cleanly to baseline demand-v1 without crashing or returning 0.
        """
        ml = MLDemandForecaster()
        obs = _make_obs(n=12, rps=250.0)

        # Force _solve_ridge to raise an exception simulating numerical instability
        with patch("app.engine.ml_forecaster._solve_ridge", side_effect=ZeroDivisionError("Singular matrix")):
            fc = ml.predict(obs, forecast_horizon_seconds=300)
            assert isinstance(fc, DemandForecast)
            # Must fall back to baseline model
            assert fc.model_version == "demand-v1"
            assert fc.predicted_legitimate_rps > 0.0
            assert 200.0 <= fc.predicted_legitimate_rps <= 300.0

    def test_ml_nan_prediction_falls_back_to_baseline(self):
        """If ML produces non-finite float, falls back to baseline."""
        ml = MLDemandForecaster()
        obs = _make_obs(n=12, rps=300.0)

        with patch.object(ml, "_heuristic_ridge_projection", return_value=float("nan")):
            # Force small dataset to use _heuristic_ridge_projection (n=5)
            small_obs = _make_obs(n=5, rps=300.0)
            fc = ml.predict(small_obs, forecast_horizon_seconds=300)
            assert isinstance(fc, DemandForecast)
            assert fc.model_version == "demand-v1"
            assert fc.predicted_legitimate_rps > 0.0
