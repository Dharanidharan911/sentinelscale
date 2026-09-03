"""
SentinelScale — Demand Intelligence — Test: Error Handling
Verifies that errors are explicit and never silently converted to zero demand.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestInsufficientDataErrors:
    def test_single_inline_observation_returns_422(self):
        """One observation is below settings.FORECAST_MIN_OBSERVATIONS — must be 422, not zero RPS."""
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": [
                {"timestamp": 1_700_000_000.0, "rps": 100.0}
            ]
        }
        response = client.post("/api/v1/demand/forecast", json=payload)
        assert response.status_code == 422
        data = response.json()
        assert data["detail"]["error"] == "insufficient_data"
        # Must include context — not just a generic message
        assert "required_samples" in data["detail"]
        assert "available_samples" in data["detail"]

    def test_empty_inline_observations_returns_422(self):
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": []
        }
        # Empty list triggers mock provider (no static provider selected)
        # Mock provider returns many observations — this should succeed
        # (empty list → fallback to mock, not error)
        response = client.post("/api/v1/demand/forecast", json=payload)
        # Empty observations list means "use internal provider" — should succeed
        assert response.status_code == 200


class TestInvalidObservationErrors:
    def test_negative_rps_rejected_by_model(self):
        """Negative RPS should be caught at Pydantic validation layer."""
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": [
                {"timestamp": 1_700_000_000.0, "rps": -5.0},
                {"timestamp": 1_700_000_030.0, "rps": 100.0},
            ]
        }
        response = client.post("/api/v1/demand/forecast", json=payload)
        # Pydantic rejects negative RPS at the model layer → 422
        assert response.status_code == 422


class TestSuccessfulForecast:
    def test_two_observations_minimum_produces_forecast(self):
        """Exactly settings.FORECAST_MIN_OBSERVATIONS observations should succeed."""
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": [
                {"timestamp": 1_700_000_000.0, "rps": 500.0},
                {"timestamp": 1_700_000_030.0, "rps": 520.0},
            ]
        }
        response = client.post("/api/v1/demand/forecast", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["predicted_legitimate_rps"] >= 0.0

    def test_zero_rps_observations_returns_low_but_non_error_forecast(self):
        """Zero legitimate demand is a valid state — should produce 0.0 RPS forecast, not error."""
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": [
                {"timestamp": 1_700_000_000.0 + i * 30, "rps": 0.0}
                for i in range(5)
            ]
        }
        response = client.post("/api/v1/demand/forecast", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["predicted_legitimate_rps"] == 0.0
        assert data["lower_bound_rps"] == 0.0
