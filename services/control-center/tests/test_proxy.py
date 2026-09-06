import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import httpx
from app.main import app

client = TestClient(app)


@pytest.mark.asyncio
async def test_proxy_version_success():
    mock_response = httpx.Response(
        200,
        json={
            "service": "platform",
            "dry_run": True,
            "shadow_mode": True,
            "autonomous_actions_enabled": False
        },
        request=httpx.Request("GET", "http://platform:8003/version")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp = client.get("/api/proxy/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "platform"
        assert data["dry_run"] is True
        assert data["shadow_mode"] is True


@pytest.mark.asyncio
async def test_proxy_resources_current_success():
    mock_response = httpx.Response(
        200,
        json={
            "target_workload": "demo-api",
            "running_pods": 3,
            "cpu_utilization": 0.45,
            "memory_utilization": 0.32,
            "current_capacity_rps": 150.0
        },
        request=httpx.Request("GET", "http://platform:8003/api/v1/resources/current")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp = client.get("/api/proxy/resources/current?namespace=default&workload=demo-api")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running_pods"] == 3
        assert data["current_capacity_rps"] == 150.0


@pytest.mark.asyncio
async def test_proxy_history_success():
    mock_response = httpx.Response(
        200,
        json=[
            {
                "id": "obs-123",
                "action": "HOLD",
                "recommended_pods": 3,
                "baseline_hpa_recommended_pods": 4,
                "pod_delta_vs_baseline": -1,
                "traffic_risk": 0.85
            }
        ],
        request=httpx.Request("GET", "http://platform:8003/api/v1/history")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp = client.get("/api/proxy/history?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["action"] == "HOLD"
        assert data[0]["pod_delta_vs_baseline"] == -1


@pytest.mark.asyncio
async def test_proxy_orchestrate_decision_success():
    mock_response = httpx.Response(
        200,
        json={
            "decision_id": "dec-999",
            "event_id": "evt-888",
            "trace_id": "0123456789abcdef0123456789abcdef",
            "timestamp": "2026-09-06T14:30:00Z",
            "contract_version": "1.0.0",
            "service_version": "0.1.0",
            "model_version": "0.1.0",
            "action": "HOLD",
            "reason": "High security risk (0.92) detected with malicious traffic. Predicted legitimate demand (45.0 RPS) is within current capacity (150.0 RPS). Prevented reactive overprovisioning of 1 pods.",
            "confidence": 0.98,
            "traffic_risk": 0.92,
            "predicted_legitimate_rps": 45.0,
            "current_capacity_rps": 150.0,
            "current_pods": 3,
            "recommended_pods": 3,
            "baseline_hpa_recommended_pods": 4,
            "pod_delta_vs_baseline": -1,
            "policy": "default_safety_policy",
            "dry_run": True,
            "shadow_mode": True
        },
        request=httpx.Request("POST", "http://platform:8003/api/v1/decision/orchestrate")
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        resp = client.post("/api/proxy/decision/orchestrate", json={"namespace": "default", "workload": "demo-api"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "HOLD"
        assert data["recommended_pods"] == 3
        assert data["baseline_hpa_recommended_pods"] == 4
        assert data["pod_delta_vs_baseline"] == -1
        assert "Prevented reactive overprovisioning" in data["reason"]
        assert data["confidence"] == 0.98
        assert data["traffic_risk"] == 0.92
        assert data["dry_run"] is True


@pytest.mark.asyncio
async def test_proxy_aggregate_decision_success():
    mock_response = httpx.Response(
        200,
        json={
            "context_id": "ctx-100",
            "trace_id": "trace-agg-123",
            "timestamp": "2026-09-06T14:30:00Z",
            "contract_version": "1.0.0",
            "target_workload": "demo-api",
            "traffic_assessment": {
                "assessment_id": "ass-01",
                "timestamp": "2026-09-06T14:30:00Z",
                "classification": "malicious",
                "risk_score": 0.92,
                "confidence": 0.95,
                "total_rps": 180.0,
                "legitimate_rps_estimate": 45.0,
                "suspicious_rps_estimate": 135.0,
                "top_signals": ["rapid_ip_fanout", "rate_limited_surge"],
                "contract_version": "1.0.0"
            },
            "demand_forecast": {
                "forecast_id": "fc-01",
                "timestamp": "2026-09-06T14:30:00Z",
                "target_workload": "demo-api",
                "predicted_legitimate_rps": 45.0,
                "confidence": 0.95,
                "lower_bound_rps": 40.0,
                "upper_bound_rps": 50.0,
                "forecast_horizon_seconds": 300,
                "contract_version": "1.0.0"
            },
            "resource_state": {
                "running_pods": 3,
                "current_capacity_rps": 150.0,
                "cpu_utilization": 0.78
            },
            "dry_run": True,
            "shadow_mode": True
        },
        request=httpx.Request("POST", "http://platform:8003/api/v1/decision/aggregate")
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        resp = client.post("/api/proxy/decision/aggregate", json={"namespace": "default", "workload": "demo-api"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["traffic_assessment"]["classification"] == "malicious"
        assert data["demand_forecast"]["predicted_legitimate_rps"] == 45.0
        assert "rapid_ip_fanout" in data["traffic_assessment"]["top_signals"]


@pytest.mark.asyncio
async def test_proxy_graceful_failure_on_upstream_unreachable():
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
        resp = client.get("/api/proxy/version")
        assert resp.status_code == 502
        assert "Unable to connect to Platform" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_proxy_upstream_error_passthrough():
    mock_response = httpx.Response(
        404,
        text="Workload not found",
        request=httpx.Request("GET", "http://platform:8003/api/v1/resources/current")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp = client.get("/api/proxy/resources/current?workload=nonexistent")
        assert resp.status_code == 404
        assert "404" in resp.json()["detail"]


