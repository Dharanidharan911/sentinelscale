from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_forecast_demand_endpoint():
    payload = {
        "forecast_horizon_seconds": 300,
        "target_service": "demo-api",
        "trace_id": "test-trace-demand-123"
    }
    response = client.post("/api/v1/demand/forecast", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["trace_id"] == "test-trace-demand-123"
    assert "event_id" in data
    assert data["forecast_horizon_seconds"] == 300
    assert data["predicted_legitimate_rps"] >= 0.0
    assert data["lower_bound_rps"] <= data["predicted_legitimate_rps"] <= data["upper_bound_rps"]
    assert 0.0 <= data["confidence"] <= 1.0
