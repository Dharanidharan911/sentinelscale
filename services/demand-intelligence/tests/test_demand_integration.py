"""
SentinelScale — Demand Intelligence — Test: DemandForecast Integration (M2-8)
Validates end-to-end integration of DemandForecast contract (v1.0.0) from the
perspective of an external caller (e.g. Decision Engine / Platform client),
strictly self-contained within Member 2 without importing Member 3 code.
"""
import json
from pathlib import Path
import jsonschema
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.demand import DemandForecast

client = TestClient(app)

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "demand" / "demand_forecast.schema.json"


@pytest.fixture(scope="module")
def demand_forecast_schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _validate_schema(payload: dict, schema: dict):
    jsonschema.validate(instance=payload, schema=schema)


def test_integration_client_flow_default_mock(demand_forecast_schema):
    """Simulate an external client calling forecast endpoint without inline observations."""
    response = client.post(
        "/api/v1/demand/forecast",
        json={"forecast_horizon_seconds": 300, "trace_id": "client-trace-001"},
    )
    assert response.status_code == 200
    data = response.json()
    _validate_schema(data, demand_forecast_schema)

    # Validate Pydantic model hydration
    forecast = DemandForecast.model_validate(data)
    assert forecast.trace_id == "client-trace-001"
    assert forecast.forecast_horizon_seconds == 300
    assert forecast.contract_version == "1.0.0"
    assert forecast.predicted_legitimate_rps >= 0.0
    assert forecast.lower_bound_rps <= forecast.predicted_legitimate_rps <= forecast.upper_bound_rps
    assert 0.0 <= forecast.confidence <= 1.0


def test_integration_client_flow_with_inline_observations(demand_forecast_schema):
    """Simulate client providing explicit upstream observations."""
    base_time = 1700000000.0
    observations = [
        {"timestamp": base_time + i * 30.0, "rps": 200.0 + i * 5.0}
        for i in range(10)
    ]
    response = client.post(
        "/api/v1/demand/forecast",
        json={
            "forecast_horizon_seconds": 120,
            "trace_id": "client-trace-inline",
            "observations": observations,
        },
    )
    assert response.status_code == 200
    data = response.json()
    _validate_schema(data, demand_forecast_schema)

    forecast = DemandForecast.model_validate(data)
    assert forecast.trace_id == "client-trace-inline"
    assert forecast.forecast_horizon_seconds == 120
    assert forecast.predicted_legitimate_rps >= 200.0


def test_integration_client_zero_rps_valid_demand(demand_forecast_schema):
    """
    Zero RPS is a physically valid legitimate workload state (e.g. idle service or maintenance).
    It must produce a successful 200 response with predicted RPS == 0.0, not an error.
    """
    base_time = 1700000000.0
    observations = [
        {"timestamp": base_time + i * 30.0, "rps": 0.0}
        for i in range(8)
    ]
    response = client.post(
        "/api/v1/demand/forecast",
        json={
            "forecast_horizon_seconds": 300,
            "trace_id": "client-trace-zero",
            "observations": observations,
        },
    )
    assert response.status_code == 200
    data = response.json()
    _validate_schema(data, demand_forecast_schema)

    forecast = DemandForecast.model_validate(data)
    assert forecast.predicted_legitimate_rps == 0.0
    assert forecast.lower_bound_rps == 0.0
    assert forecast.upper_bound_rps >= 0.0
    assert 0.0 <= forecast.confidence <= 1.0


def test_integration_client_header_trace_propagation(demand_forecast_schema):
    """Client passes X-Trace-ID header; it must be echoed in body and response header."""
    response = client.post(
        "/api/v1/demand/forecast",
        json={"forecast_horizon_seconds": 60},
        headers={"X-Trace-ID": "header-trace-999"},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Trace-ID") == "header-trace-999"
    data = response.json()
    _validate_schema(data, demand_forecast_schema)
    assert data["trace_id"] == "header-trace-999"


def test_integration_client_boundary_horizons(demand_forecast_schema):
    """Test short horizon (1s) and long horizon (3600s)."""
    for horizon in [1, 60, 600, 3600]:
        response = client.post(
            "/api/v1/demand/forecast",
            json={"forecast_horizon_seconds": horizon},
        )
        assert response.status_code == 200
        data = response.json()
        _validate_schema(data, demand_forecast_schema)
        assert data["forecast_horizon_seconds"] == horizon
