from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_assess_traffic_endpoint_default():
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


def test_assess_traffic_endpoint_with_telemetry():
    payload = {
        "window_seconds": 60,
        "target_service": "demo-api",
        "trace_id": "trace-telemetry-456",
        "telemetry": {
            "total_requests": 6000,
            "total_rps": 100.0,
            "baseline_rps": 100.0,
            "status_codes": {
                "status_2xx": 5900,
                "status_3xx": 50,
                "status_4xx": 40,
                "status_5xx": 10
            },
            "top_ip_ratio": 0.04,
            "unique_ip_count": 800,
            "non_standard_ua_ratio": 0.02,
            "single_endpoint_ratio": 0.30
        }
    }
    response = client.post("/api/v1/traffic/assess", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["trace_id"] == "trace-telemetry-456"
    assert data["total_rps"] == 100.0
    assert data["classification"] == "legitimate"
    assert data["risk_score"] <= 0.25
    assert data["legitimacy_score"] >= 0.70
    assert "legitimate_traffic_profile" in data["top_signals"]


def test_assess_traffic_endpoint_invalid_payload():
    # Invalid negative total_rps
    payload = {
        "window_seconds": 60,
        "telemetry": {
            "total_requests": 100,
            "total_rps": -5.0
        }
    }
    response = client.post("/api/v1/traffic/assess", json=payload)
    assert response.status_code == 422


def test_assess_traffic_endpoint_trace_header():
    # Header X-Trace-ID handling
    headers = {"X-Trace-ID": "header-trace-999"}
    response = client.post("/api/v1/traffic/assess", json={"window_seconds": 60}, headers=headers)
    assert response.status_code == 200
    assert response.json()["trace_id"] == "header-trace-999"
