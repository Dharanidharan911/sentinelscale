from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_assess_traffic_endpoint():
    payload = {
        "window_seconds": 60,
        "target_service": "demo-api",
        "trace_id": "test-trace-123"
    }
    response = client.post("/api/v1/traffic/assess", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["trace_id"] == "test-trace-123"
    assert "event_id" in data
    assert data["window_seconds"] == 60
    assert data["total_rps"] >= 0.0
    assert 0.0 <= data["risk_score"] <= 1.0
    assert 0.0 <= data["legitimacy_score"] <= 1.0
    assert 0.0 <= data["confidence"] <= 1.0
    assert data["classification"] in ["legitimate", "suspicious", "malicious", "unknown"]
    assert isinstance(data["top_signals"], list)
