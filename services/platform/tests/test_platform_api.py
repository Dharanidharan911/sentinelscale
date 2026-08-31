import uuid
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def get_sample_context():
    return {
        "context_id": str(uuid.uuid4()),
        "trace_id": "test-trace-platform-123",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "contract_version": "1.0.0",
        "target_workload": "demo-api",
        "traffic_assessment": {
            "event_id": str(uuid.uuid4()),
            "trace_id": "test-trace-platform-123",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "contract_version": "1.0.0",
            "service_version": "0.1.0",
            "model_version": "traffic-v0 (mock)",
            "window_seconds": 60,
            "total_rps": 2500.0,
            "legitimate_rps_estimate": 850.0,
            "suspicious_rps_estimate": 1650.0,
            "risk_score": 0.84,
            "legitimacy_score": 0.34,
            "confidence": 0.91,
            "classification": "suspicious",
            "top_signals": ["high_burst_rate"]
        },
        "demand_forecast": {
            "event_id": str(uuid.uuid4()),
            "trace_id": "test-trace-platform-123",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "contract_version": "1.0.0",
            "service_version": "0.1.0",
            "model_version": "demand-v0 (mock)",
            "forecast_horizon_seconds": 300,
            "predicted_legitimate_rps": 1100.0,
            "lower_bound_rps": 950.0,
            "upper_bound_rps": 1250.0,
            "confidence": 0.91
        },
        "resource_state": {
            "event_id": str(uuid.uuid4()),
            "trace_id": "test-trace-platform-123",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "contract_version": "1.0.0",
            "service_version": "0.1.0",
            "target_namespace": "sentinelscale",
            "target_workload": "demo-api",
            "cpu_utilization": 0.75,
            "memory_utilization": 0.50,
            "cpu_requested_cores": 4.0,
            "cpu_limit_cores": 8.0,
            "memory_requested_bytes": 4294967296,
            "memory_limit_bytes": 8589934592,
            "running_pods": 4,
            "desired_pods": 4,
            "pending_pods": 0,
            "request_rate": 2500.0,
            "p95_latency_ms": 45.0,
            "error_rate": 0.001,
            "current_capacity_rps": 1400.0,
            "estimated_required_capacity_rps": 1200.0,
            "estimated_resource_waste": 0.14
        },
        "dry_run": True,
        "shadow_mode": True
    }


def test_get_current_resources_endpoint():
    response = client.get("/api/v1/resources/current?namespace=sentinelscale&workload=demo-api")
    assert response.status_code == 200
    data = response.json()
    assert data["target_namespace"] == "sentinelscale"
    assert data["target_workload"] == "demo-api"
    assert data["running_pods"] >= 0
    assert data["cpu_utilization"] >= 0.0


def test_evaluate_decision_endpoint():
    payload = get_sample_context()
    response = client.post("/api/v1/decision/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["action"] in ["SCALE", "RATE_LIMIT", "MITIGATE", "HOLD"]
    assert "reason" in data
    assert data["dry_run"] is True
    assert data["shadow_mode"] is True
    assert "baseline_hpa_recommended_pods" in data
    assert "recommended_pods" in data
