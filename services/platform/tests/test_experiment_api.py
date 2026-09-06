import json
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.experiments.reader import ExperimentResultsReader, get_experiment_reader


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_list_experiments_all():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/v1/experiments")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 6
        
        # Verify fields on summary
        first = data[0]
        assert "run_id" in first
        assert "scenario_id" in first
        assert "scenario_name" in first
        assert "start_time" in first
        assert "end_time" in first
        assert "workload_summary" in first
        assert "hpa_summary" in first
        assert "sentinelscale_summary" in first
        assert "comparison_summary" in first
        assert "performance_guardrails" in first
        assert "safety" in first
        assert "has_timeseries" in first
        # Timeseries array itself should not be present in summary
        assert "timeseries" not in first

        # Check descending sort order
        start_times = [item["start_time"] for item in data]
        assert start_times == sorted(start_times, reverse=True)


@pytest.mark.asyncio
async def test_list_experiments_filter_scenario():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/v1/experiments", params={"scenario_id": "scenario_a_normal"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["scenario_id"] == "scenario_a_normal"
        assert data[0]["run_id"] == "EXP-20260906-001"


@pytest.mark.asyncio
async def test_get_experiment_by_run_id_success():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/v1/experiments/EXP-20260906-001")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "EXP-20260906-001"
        assert data["scenario_id"] == "scenario_a_normal"
        assert "timeseries" in data
        assert isinstance(data["timeseries"], list)
        assert len(data["timeseries"]) > 0

        # Verify timeseries structure
        ts0 = data["timeseries"][0]
        assert "timestamp" in ts0
        assert "elapsed_seconds" in ts0
        assert "hpa_replicas" in ts0
        assert "sentinelscale_recommended_pods" in ts0
        assert "replica_delta" in ts0


@pytest.mark.asyncio
async def test_get_experiment_by_run_id_not_found():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/v1/experiments/EXP-NONEXISTENT-999")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()


@pytest.mark.asyncio
async def test_all_experiments_safety_invariants():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/v1/experiments")
        assert response.status_code == 200
        experiments = response.json()
        for exp in experiments:
            safety = exp["safety"]
            assert safety["dry_run"] is True
            assert safety["shadow_mode"] is True
            assert safety["sentinel_mutations_count"] == 0
            assert safety["autonomous_actions_enabled"] is False


def test_reader_handles_malformed_and_missing_directory(tmp_path):
    # Test missing dir
    missing_reader = ExperimentResultsReader(results_dir=str(tmp_path / "does_not_exist"))
    assert missing_reader.list_experiments() == []
    assert missing_reader.get_experiment("any") is None

    # Test malformed files
    valid_data = {
        "run_id": "EXP-MOCK-001",
        "scenario_id": "scenario_mock",
        "scenario_name": "Mock Scenario",
        "start_time": "2026-09-06T12:00:00Z",
        "end_time": "2026-09-06T12:05:00Z",
        "duration_seconds": 300.0,
        "phases": [],
        "workload_summary": {
            "total_requests": 100,
            "average_rps": 10.0,
            "peak_rps": 20.0,
            "error_rate": 0.0,
            "p50_latency_ms": 5.0,
            "p95_latency_ms": 10.0
        },
        "hpa_summary": {
            "initial_replicas": 2,
            "final_replicas": 2,
            "peak_replicas": 2,
            "min_replicas": 2,
            "pod_seconds": 600.0,
            "replica_hours": 0.166
        },
        "sentinelscale_summary": {
            "initial_recommended_pods": 2,
            "final_recommended_pods": 2,
            "peak_recommended_pods": 2,
            "min_recommended_pods": 2,
            "pod_seconds": 600.0,
            "replica_hours": 0.166,
            "decisions_count": 10,
            "action_distribution": {"HOLD": 10}
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
            "observed_p95_latency_ms": 10.0,
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
        "timeseries": []
    }

    test_dir = tmp_path / "experiments"
    test_dir.mkdir()
    (test_dir / "valid.json").write_text(json.dumps(valid_data), encoding="utf-8")
    (test_dir / "corrupted.json").write_text("NOT JSON CONTENT", encoding="utf-8")
    (test_dir / "invalid_schema.json").write_text(json.dumps({"invalid": "data"}), encoding="utf-8")

    reader = ExperimentResultsReader(results_dir=str(test_dir))
    results = reader.list_experiments()
    assert len(results) == 1
    assert results[0].run_id == "EXP-MOCK-001"
    
    assert reader.get_experiment("EXP-MOCK-001") is not None
    assert reader.get_experiment("corrupted") is None

