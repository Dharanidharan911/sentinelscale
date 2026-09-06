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
            "action": "HOLD",
            "recommended_pods": 3,
            "baseline_hpa_recommended_pods": 4,
            "pod_delta_vs_baseline": -1,
            "reason": "High traffic risk with legitimate demand in capacity.",
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
        assert data["dry_run"] is True


@pytest.mark.asyncio
async def test_proxy_graceful_failure_on_upstream_unreachable():
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
        resp = client.get("/api/proxy/version")
        assert resp.status_code == 502
        assert "Unable to connect to Platform" in resp.json()["detail"]

