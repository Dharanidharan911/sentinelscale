"""
SentinelScale — Demand Intelligence — Provider & Forecaster Architecture Tests (M2-7)
Validates configurable engine and provider selection, contract invariance, and error propagation.
"""
import json
from pathlib import Path
import pytest
import jsonschema

from app.models.demand import DemandObservation, ForecastRequest
from app.providers.mock_provider import MockDemandProvider
from app.providers.static_provider import StaticObservationProvider
from app.services.forecaster import DemandForecastingService


@pytest.fixture
def json_schema():
    schema_path = (
        Path(__file__).parent.parent.parent.parent
        / "contracts"
        / "demand"
        / "demand_forecast.schema.json"
    )
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _make_observations(rps_values, start_time=1700000000.0, step=30.0):
    return [
        DemandObservation(timestamp=start_time + i * step, rps=float(rps))
        for i, rps in enumerate(rps_values)
    ]


@pytest.mark.asyncio
async def test_service_defaults_to_baseline_engine(json_schema):
    service = DemandForecastingService()
    req = ForecastRequest(forecast_horizon_seconds=300, trace_id="trace-arch-baseline")
    forecast = await service.forecast_demand(req)

    assert forecast.model_version == "demand-v1"
    assert forecast.contract_version == "1.0.0"
    assert forecast.trace_id == "trace-arch-baseline"
    jsonschema.validate(instance=forecast.model_dump(), schema=json_schema)


@pytest.mark.asyncio
async def test_service_executes_ml_engine_when_configured(json_schema):
    service = DemandForecastingService(model_type="ml")
    req = ForecastRequest(forecast_horizon_seconds=300, trace_id="trace-arch-ml")
    forecast = await service.forecast_demand(req)

    assert forecast.model_version == "demand-ml-v1"
    assert forecast.contract_version == "1.0.0"
    assert forecast.trace_id == "trace-arch-ml"
    jsonschema.validate(instance=forecast.model_dump(), schema=json_schema)


@pytest.mark.asyncio
async def test_service_ml_with_inline_observations(json_schema):
    obs = _make_observations([700.0, 710.0, 720.0, 730.0, 740.0, 750.0, 760.0])
    service = DemandForecastingService(model_type="demand-ml-v1")
    req = ForecastRequest(
        forecast_horizon_seconds=120,
        observations=obs,
        trace_id="trace-arch-inline-ml",
    )
    forecast = await service.forecast_demand(req)

    assert forecast.model_version == "demand-ml-v1"
    assert forecast.predicted_legitimate_rps > 700.0
    assert forecast.lower_bound_rps <= forecast.predicted_legitimate_rps <= forecast.upper_bound_rps
    jsonschema.validate(instance=forecast.model_dump(), schema=json_schema)


@pytest.mark.asyncio
async def test_service_ml_fallback_on_sparse_observations(json_schema):
    # Only 3 observations: ML falls back to baseline demand-v1
    obs = _make_observations([500.0, 520.0, 510.0])
    service = DemandForecastingService(model_type="ml")
    req = ForecastRequest(
        forecast_horizon_seconds=180,
        observations=obs,
        trace_id="trace-arch-sparse-fallback",
    )
    forecast = await service.forecast_demand(req)

    assert forecast.model_version == "demand-v1"
    assert forecast.predicted_legitimate_rps > 0.0
    jsonschema.validate(instance=forecast.model_dump(), schema=json_schema)
