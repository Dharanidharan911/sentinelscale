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


@pytest.mark.asyncio
async def test_proxy_history_stats_success():
    mock_response = httpx.Response(
        200,
        json={
            "total_observations": 42,
            "successful_observations": 40,
            "failed_observations": 2,
            "success_rate": 0.952,
            "retention_days": 7
        },
        request=httpx.Request("GET", "http://platform:8003/api/v1/history/stats")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp = client.get("/api/proxy/history/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_observations"] == 42
        assert data["success_rate"] == 0.952


@pytest.mark.asyncio
async def test_proxy_history_observation_by_id():
    mock_response = httpx.Response(
        200,
        json={
            "id": "obs-abc-123",
            "decision_id": "dec-abc-123",
            "action": "HOLD",
            "recommended_pods": 3
        },
        request=httpx.Request("GET", "http://platform:8003/api/v1/history/obs-abc-123")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp = client.get("/api/proxy/history/obs-abc-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "obs-abc-123"
        assert data["action"] == "HOLD"


@pytest.mark.asyncio
async def test_proxy_intelligence_summary_success():
    mock_response = httpx.Response(
        200,
        json={
            "window": "1h",
            "observation_count": 12,
            "average_traffic_risk": 0.45,
            "average_predicted_demand_rps": 65.0
        },
        request=httpx.Request("GET", "http://platform:8003/api/v1/intelligence/history/summary")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp = client.get("/api/proxy/intelligence/summary?window=1h")
        assert resp.status_code == 200
        data = resp.json()
        assert data["observation_count"] == 12
        assert data["average_traffic_risk"] == 0.45


@pytest.mark.asyncio
async def test_proxy_intelligence_trends_success():
    mock_response = httpx.Response(
        200,
        json={
            "window": "1h",
            "total_buckets": 2,
            "buckets": [
                {
                    "bucket_start": "2026-09-06T14:00:00Z",
                    "bucket_end": "2026-09-06T14:30:00Z",
                    "total_observations": 6,
                    "average_predicted_legitimate_rps": 50.0,
                    "average_traffic_risk": 0.3,
                    "average_current_capacity_rps": 150.0,
                    "average_recommended_pods": 3.0,
                    "average_baseline_hpa_pods": 4.0
                }
            ]
        },
        request=httpx.Request("GET", "http://platform:8003/api/v1/intelligence/history/trends")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp = client.get("/api/proxy/intelligence/trends?window=1h")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_buckets"] == 2
        assert len(data["buckets"]) == 1
        assert data["buckets"][0]["average_recommended_pods"] == 3.0


@pytest.mark.asyncio
async def test_proxy_intelligence_anomalies_success():
    mock_response = httpx.Response(
        200,
        json={
            "observation_id": "obs-latest",
            "timestamp": "2026-09-06T14:30:00Z",
            "overall_severity": "ELEVATED",
            "signals": [
                {
                    "metric": "traffic_risk",
                    "current_value": 0.85,
                    "baseline_mean": 0.20,
                    "baseline_stddev": 0.10,
                    "deviation": 0.65,
                    "z_score": 6.5,
                    "severity": "ELEVATED",
                    "direction": "HIGHER_THAN_BASELINE",
                    "sample_count": 15,
                    "interpretation": "Traffic risk significantly above historical baseline."
                }
            ],
            "explanation": "Traffic risk is elevated compared to historical baseline.",
            "pattern_notes": ["Sudden surge in malicious traffic"]
        },
        request=httpx.Request("GET", "http://platform:8003/api/v1/intelligence/anomalies")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp = client.get("/api/proxy/intelligence/anomalies?window=1h")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_severity"] == "ELEVATED"
        assert len(data["signals"]) == 1
        assert data["signals"][0]["z_score"] == 6.5


@pytest.mark.asyncio
async def test_proxy_experiments_list_success():
    mock_response = httpx.Response(
        200,
        json=[
            {
                "run_id": "EXP-20260906-001",
                "scenario_id": "scenario_a_normal",
                "scenario_name": "Scenario A — Normal / Low Demand",
                "start_time": "2026-09-05T19:58:23.051066+00:00",
                "end_time": "2026-09-05T19:59:42.946392+00:00",
                "duration_seconds": 79.9,
                "workload_summary": {
                    "total_requests": 1226,
                    "average_rps": 24.5,
                    "peak_rps": 36.75,
                    "error_rate": 0.0,
                    "p50_latency_ms": 7.34,
                    "p95_latency_ms": 13.47
                },
                "hpa_summary": {
                    "initial_replicas": 2,
                    "final_replicas": 2,
                    "peak_replicas": 2,
                    "min_replicas": 2,
                    "pod_seconds": 157.72,
                    "replica_hours": 0.0438
                },
                "sentinelscale_summary": {
                    "initial_recommended_pods": 2,
                    "final_recommended_pods": 2,
                    "peak_recommended_pods": 2,
                    "min_recommended_pods": 2,
                    "pod_seconds": 157.72,
                    "replica_hours": 0.0438,
                    "decisions_count": 19,
                    "action_distribution": {"HOLD": 19}
                },
                "comparison_summary": {
                    "pod_seconds_delta": 0.0,
                    "replica_hours_delta": 0.0,
                    "max_replica_difference": 0,
                    "divergence_classification": "agreement",
                    "performance_guardrails_passed": True
                },
                "performance_guardrails": {
                    "p95_latency_guardrail_ms": 1000.0,
                    "observed_p95_latency_ms": 13.47,
                    "error_rate_guardrail": 0.05,
                    "observed_error_rate": 0.0,
                    "guardrails_passed": True
                },
                "safety": {
                    "dry_run": True,
                    "shadow_mode": True,
                    "sentinel_mutations_count": 0,
                    "autonomous_actions_enabled": False
                },
                "has_timeseries": True
            }
        ],
        request=httpx.Request("GET", "http://platform:8003/api/v1/experiments")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp = client.get("/api/proxy/experiments?scenario_id=scenario_a_normal")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["run_id"] == "EXP-20260906-001"
        assert data[0]["comparison_summary"]["divergence_classification"] == "agreement"


@pytest.mark.asyncio
async def test_proxy_experiment_detail_success():
    mock_response = httpx.Response(
        200,
        json={
            "run_id": "EXP-20260906-001",
            "scenario_id": "scenario_a_normal",
            "scenario_name": "Scenario A — Normal / Low Demand",
            "start_time": "2026-09-05T19:58:23.051066+00:00",
            "end_time": "2026-09-05T19:59:42.946392+00:00",
            "duration_seconds": 79.9,
            "phases": [],
            "workload_summary": {
                "total_requests": 1226,
                "average_rps": 24.5,
                "peak_rps": 36.75,
                "error_rate": 0.0,
                "p50_latency_ms": 7.34,
                "p95_latency_ms": 13.47
            },
            "hpa_summary": {
                "initial_replicas": 2,
                "final_replicas": 2,
                "peak_replicas": 2,
                "min_replicas": 2,
                "pod_seconds": 157.72,
                "replica_hours": 0.0438
            },
            "sentinelscale_summary": {
                "initial_recommended_pods": 2,
                "final_recommended_pods": 2,
                "peak_recommended_pods": 2,
                "min_recommended_pods": 2,
                "pod_seconds": 157.72,
                "replica_hours": 0.0438,
                "decisions_count": 19,
                "action_distribution": {"HOLD": 19}
            },
            "comparison_summary": {
                "pod_seconds_delta": 0.0,
                "replica_hours_delta": 0.0,
                "max_replica_difference": 0,
                "divergence_classification": "agreement",
                "performance_guardrails_passed": True
            },
            "performance_guardrails": {
                "p95_latency_guardrail_ms": 1000.0,
                "observed_p95_latency_ms": 13.47,
                "error_rate_guardrail": 0.05,
                "observed_error_rate": 0.0,
                "guardrails_passed": True
            },
            "safety": {
                "dry_run": True,
                "shadow_mode": True,
                "sentinel_mutations_count": 0,
                "autonomous_actions_enabled": False
            },
            "timeseries": [
                {
                    "timestamp": "2026-09-05T19:58:25.181687+00:00",
                    "elapsed_seconds": 1.04,
                    "hpa_replicas": 2,
                    "hpa_desired_replicas": 2,
                    "hpa_cpu_percent": 4,
                    "sentinelscale_recommended_pods": 2,
                    "replica_delta": 0,
                    "sentinelscale_action": "HOLD",
                    "decision_reason": "Normal legitimate demand."
                }
            ]
        },
        request=httpx.Request("GET", "http://platform:8003/api/v1/experiments/EXP-20260906-001")
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp = client.get("/api/proxy/experiments/EXP-20260906-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "EXP-20260906-001"
        assert len(data["timeseries"]) == 1
        assert data["timeseries"][0]["sentinelscale_action"] == "HOLD"

