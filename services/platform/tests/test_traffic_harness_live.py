"""
SentinelScale — Live Integration Test for Stage F1 Traffic Harness
Tests running scenarios against live demo-api (:8000) and traffic-intelligence (:8001).
Skipped cleanly if live services are not reachable.
"""
import httpx
import pytest
from app.harness.models import TrafficScenarioType, create_scenario_preset
from app.harness.runner import ScenarioRunner


async def _check_service_reachability(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(f"{url}/health")
            return resp.status_code == 200
    except Exception:
        return False


@pytest.mark.asyncio
async def test_live_traffic_harness_scenarios_optional():
    """Run all 4 canonical scenarios against live demo-api and M1 services if available."""
    demo_api_url = "http://localhost:8000"
    traffic_url = "http://localhost:8001"

    demo_live = await _check_service_reachability(demo_api_url)
    m1_live = await _check_service_reachability(traffic_url)

    if not (demo_live and m1_live):
        pytest.skip("Live demo-api (:8000) and/or traffic-intelligence (:8001) not reachable — skipping live test.")

    runner = ScenarioRunner(
        demo_api_url=demo_api_url,
        traffic_intelligence_url=traffic_url,
    )

    for sc_type in [
        TrafficScenarioType.STEADY_LEGITIMATE,
        TrafficScenarioType.LEGITIMATE_FLASH_CROWD,
        TrafficScenarioType.HOSTILE_L7_FLOOD,
        TrafficScenarioType.MIXED_TRAFFIC,
    ]:
        scenario = create_scenario_preset(sc_type, duration_seconds=1.0)
        scenario.target_rps = 20.0
        result = await runner.run_scenario(scenario)

        assert result.total_requests_generated == 20
        assert result.assessment.contract_version == "1.0.0"
        assert result.assessment.trace_id == result.trace_id

