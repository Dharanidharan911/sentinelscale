"""
SentinelScale — Demand Intelligence — Test: Demand API Integration
Tests the full HTTP stack end-to-end via FastAPI TestClient.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _make_observations(n: int = 10, rps: float = 500.0):
    return [
        {"timestamp": 1_700_000_000.0 + i * 30, "rps": rps}
        for i in range(n)
    ]


class TestForecastDemandEndpoint:
    def test_forecast_with_explicit_trace_id(self):
        payload = {
            "forecast_horizon_seconds": 300,
            "target_service": "demo-api",
            "trace_id": "test-trace-demand-123",
            "observations": _make_observations(),
        }
        response = client.post("/api/v1/demand/forecast", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["trace_id"] == "test-trace-demand-123"
        assert "event_id" in data
        assert data["forecast_horizon_seconds"] == 300
        assert data["predicted_legitimate_rps"] >= 0.0
        assert data["lower_bound_rps"] <= data["predicted_legitimate_rps"]
        assert data["predicted_legitimate_rps"] <= data["upper_bound_rps"]
        assert 0.0 <= data["confidence"] <= 1.0

    def test_forecast_default_request_uses_mock_provider(self):
        """No observations → mock provider used → should still succeed."""
        payload = {"forecast_horizon_seconds": 300}
        response = client.post("/api/v1/demand/forecast", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["predicted_legitimate_rps"] >= 0.0

    def test_forecast_with_inline_observations(self):
        """Inline observations bypass the mock provider."""
        payload = {
            "forecast_horizon_seconds": 600,
            "observations": _make_observations(n=15, rps=850.0),
        }
        response = client.post("/api/v1/demand/forecast", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["forecast_horizon_seconds"] == 600
        # Predicted should be close to 850 for stable data
        assert 700.0 <= data["predicted_legitimate_rps"] <= 1000.0

    def test_forecast_x_trace_id_header_propagated(self):
        response = client.post(
            "/api/v1/demand/forecast",
            json={"forecast_horizon_seconds": 300, "observations": _make_observations()},
            headers={"X-Trace-ID": "header-test-trace"},
        )
        assert response.status_code == 200
        assert response.json()["trace_id"] == "header-test-trace"

    def test_forecast_response_x_trace_id_header_returned(self):
        """The service should echo the trace ID in response headers."""
        response = client.post(
            "/api/v1/demand/forecast",
            json={"forecast_horizon_seconds": 300, "observations": _make_observations()},
            headers={"X-Trace-ID": "check-response-header"},
        )
        assert response.status_code == 200
        assert response.headers.get("X-Trace-ID") == "check-response-header"

    def test_invalid_horizon_zero_rejected(self):
        response = client.post(
            "/api/v1/demand/forecast",
            json={"forecast_horizon_seconds": 0}
        )
        assert response.status_code == 422

    def test_invalid_horizon_negative_rejected(self):
        response = client.post(
            "/api/v1/demand/forecast",
            json={"forecast_horizon_seconds": -1}
        )
        assert response.status_code == 422

    def test_long_horizon_accepted(self):
        response = client.post(
            "/api/v1/demand/forecast",
            json={
                "forecast_horizon_seconds": 86400,  # 24 hours
                "observations": _make_observations(n=20),
            }
        )
        assert response.status_code == 200
        assert response.json()["forecast_horizon_seconds"] == 86400

    def test_contract_fields_all_present(self):
        required_fields = [
            "event_id", "trace_id", "generated_at", "contract_version",
            "service_version", "model_version", "forecast_horizon_seconds",
            "predicted_legitimate_rps", "lower_bound_rps", "upper_bound_rps",
            "confidence",
        ]
        response = client.post(
            "/api/v1/demand/forecast",
            json={"forecast_horizon_seconds": 300, "observations": _make_observations()},
        )
        assert response.status_code == 200
        data = response.json()
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
