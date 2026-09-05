# Module 2A — Demand Intelligence (Current Implementation)

> Service directory: `services/demand-intelligence/`
> Port: `8002`
> Owner branch: `member2/demand-intelligence`
> Last updated: 2026-09-01

> [!NOTE]
> "Module 2A" refers to the current Demand Intelligence implementation. "Module 2B" refers to the next planned phase: Hybrid Prometheus + Kubernetes Telemetry Aggregation in Module 3. These are separate concepts.
> See [`docs/MODULE_2B.md`](MODULE_2B.md) for Phase 2B.

---

## Responsibility

Module 2 independently forecasts future legitimate workload demand. It answers: *"How many RPS of genuine business traffic should we expect in the next N seconds?"*

**Critical architectural invariant**: Module 2 operates asynchronously and independently from Module 1 (Traffic Intelligence). It does NOT call Module 1 at runtime. (ADR-002)

Output: `DemandForecast` consumed by Module 3 (Platform & Decision Engine) to compute security-aware pod recommendations.

---

## Current Implementation State: Mock (demand-v0)

All forecasting is backed by a deterministic mock generator in `app/mock/generator.py`. Tagged `demand-v0 (mock)`.

### File Structure

```
services/demand-intelligence/
├── Dockerfile
├── requirements.txt               (fastapi, uvicorn, pydantic, httpx, pytest, jsonschema)
├── app/
│   ├── main.py                    FastAPI application factory
│   ├── logging.py                 StructuredLoggingMiddleware
│   ├── api/v1/endpoints.py        FastAPI routes
│   ├── config/settings.py         pydantic-settings config
│   ├── models/
│   │   └── demand.py              DemandForecast, ForecastRequest
│   ├── mock/
│   │   └── generator.py           MockDemandDataGenerator
│   └── services/
│       └── forecaster.py          DemandForecastingService
└── tests/
    ├── test_health.py
    ├── test_demand_api.py
    └── test_contract_conformance.py
```

---

## API Endpoints

### `POST /api/v1/demand/forecast`

**Request**:
```json
{"forecast_horizon_seconds": 300, "trace_id": "optional"}
```

**Response** (DemandForecast — always these fixed values in mock):
```json
{
  "event_id": "<uuid>",
  "trace_id": "...",
  "generated_at": "...",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "model_version": "demand-v0 (mock)",
  "forecast_horizon_seconds": 300,
  "predicted_legitimate_rps": 1200.0,
  "lower_bound_rps": 1050.0,
  "upper_bound_rps": 1400.0,
  "confidence": 0.91
}
```

`forecast_horizon_seconds` is passed through in the response but the mock values do not change per horizon.

### `GET /health`, `GET /ready`, `GET /version`

Standard system health endpoints.

---

## Data Models

### `ForecastRequest` (Pydantic Model)
```python
class ForecastRequest(BaseModel):
    forecast_horizon_seconds: int = Field(default=300, ge=1)
    trace_id: Optional[str] = None
```

### `DemandForecast` (Pydantic Model)
```python
class DemandForecast(BaseModel):
    event_id: str
    trace_id: str
    generated_at: str
    contract_version: str
    service_version: str
    model_version: str
    forecast_horizon_seconds: int
    predicted_legitimate_rps: float  # >= 0.0
    lower_bound_rps: float           # >= 0.0
    upper_bound_rps: float           # >= 0.0
    confidence: float                # [0.0, 1.0]
```

**Invariant**: `lower_bound_rps <= predicted_legitimate_rps <= upper_bound_rps`

---

## Service Layer

```python
class DemandForecastingService:
    def __init__(self):
        self.mock_generator = MockDemandDataGenerator()

    async def forecast_demand(self, request: ForecastRequest) -> DemandForecast:
        return self.mock_generator.generate_forecast(
            forecast_horizon_seconds=request.forecast_horizon_seconds,
            trace_id=request.trace_id
        )
```

---

## Mock Generator

`MockDemandDataGenerator.generate_forecast()` returns deterministic:
- `predicted_legitimate_rps=1200.0`
- `lower_bound_rps=1050.0`
- `upper_bound_rps=1400.0`
- `confidence=0.91`
- `forecast_horizon_seconds` echoes from request

---

## How This Feeds into Module 3 Decision Engine

Module 3 fetches a forecast via `DemandIntelligenceClient.fetch_forecast()`:
```python
# In services/platform/app/clients/demand_client.py
response = await client.post(
    f"{self.base_url}/api/v1/demand/forecast",
    json={"forecast_horizon_seconds": 300, "trace_id": trace_id}
)
return DemandForecast.model_validate(response.json())
```

The `predicted_legitimate_rps` is then used in `DecisionEngine.evaluate_decision()`:
```python
raw_sentinel_pods = math.ceil(predicted_legitimate / pod_capacity)
```

With mock values: `ceil(1200.0 / 350.0) = 4 pods` (before guardrails).

---

## JSON Schema Contract

**File**: `contracts/demand/demand_forecast.schema.json`

Validated in `tests/test_contract_conformance.py` on every test run.

---

## Configuration (`app/config/settings.py`)

| Setting | Default | Description |
| :--- | :--- | :--- |
| `SERVICE_NAME` | `demand-intelligence` | Service identifier |
| `SERVICE_VERSION` | `0.1.0` | Service version |
| `CONTRACT_VERSION` | `1.0.0` | Contract schema version |
| `MODEL_VERSION` | `demand-v0` | Model/heuristic version |
| `ENVIRONMENT` | `development` | Runtime environment |
| `LOG_LEVEL` | `INFO` | Logging level |
| `PORT` | `8002` | Listen port |

---

## Tests (5 passing)

| Test file | Coverage |
| :--- | :--- |
| `test_health.py` | `/health` endpoint |
| `test_demand_api.py` | `POST /api/v1/demand/forecast` returns valid DemandForecast |
| `test_contract_conformance.py` | Mock output validates against JSON Schema |

Run: `$env:PYTHONPATH="$PWD\services\demand-intelligence"; python -m pytest services/demand-intelligence/tests -v`

---

## Future Implementation (Real Demand Forecasting)

When Module 2 is upgraded from mock to real forecasting:

1. **Historical telemetry ingestion**: Direct Prometheus access for historical request rate time-series (NOT via Module 1 — independent, per ADR-002)
2. **Time-series decomposition**: Trend extraction, daily/weekly seasonality, promotional event detection
3. **Probabilistic forecasting model**: Prophet, ARIMA, or similar; produces prediction intervals
4. **Multi-horizon support**: The mock ignores `forecast_horizon_seconds`; real implementation must vary per horizon
5. **Model versioning**: `MODEL_VERSION` → `demand-v1`

**Invariants that must be preserved**:
- Must return valid `DemandForecast` matching `contracts/demand/demand_forecast.schema.json`
- `lower_bound_rps <= predicted_legitimate_rps <= upper_bound_rps` must always hold
- Mock fallback in `app/mock/generator.py` must be preserved
- Module 2 must NOT call Module 1 at runtime (hard architectural rule, ADR-002)
- All existing tests must continue to pass

---

## Dependencies

```
fastapi>=0.110.0,<1.0.0
uvicorn[standard]>=0.28.0,<1.0.0
pydantic>=2.6.0,<3.0.0
pydantic-settings>=2.2.0,<3.0.0
httpx>=0.27.0,<1.0.0
pytest>=8.0.0,<9.0.0
jsonschema>=4.21.0,<5.0.0
```

Future dependencies for real forecasting (add to service-specific requirements.txt only):
- `prophet` or `statsmodels` for time-series forecasting
- `numpy`, `pandas` for data processing
