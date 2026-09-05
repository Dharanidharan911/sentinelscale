# Module 2 — Demand Intelligence

> Service directory: `services/demand-intelligence/`
> Port: `8002`
> Owner branch: `member2/demand-intelligence`
> Last updated: 2026-09-05

---

## Responsibility

Module 2 forecasts future legitimate workload demand. It answers: *"How many RPS of genuine business demand should the infrastructure prepare to serve over the next N seconds?"*

**Architectural Principle**: Module 2 operates independently and does not perform synchronous calls to Module 1. It forecasts legitimate demand from an input series of authenticated, security-gated historical `DemandObservation[]` records provided by the platform.

Output: `DemandForecast` consumed by Module 3 (Platform & Decision Engine).

---

## Implementation State: `demand-v1`

Module 2 implements a deterministic statistical forecasting engine:
- **Recency-Weighted Moving Average**: Applies exponential decay to older observations based on elapsed time.
- **Linear Trend Projection**: Projects forward using Ordinary Least Squares (OLS) slope when time span ($\ge 120\text{s}$) and sample count ($\ge 5$) warrant trend projection.
- **Confidence Scoring**: Earned based on sample size, coefficient of variation, sampling regularity, and horizon ratio.

### File Structure

```
services/demand-intelligence/
├── Dockerfile
├── requirements.txt
├── app/
│   ├── main.py                    FastAPI application factory
│   ├── logging.py                 StructuredLoggingMiddleware
│   ├── api/v1/endpoints.py        FastAPI routes
│   ├── config/settings.py         pydantic-settings config
│   ├── errors.py                  InsufficientDataError, InvalidObservationError, ProviderUnavailableError
│   ├── models/
│   │   └── demand.py              DemandForecast, ForecastRequest, DemandObservation
│   ├── mock/
│   │   └── generator.py           MockDemandDataGenerator (fallback)
│   ├── engine/
│   │   ├── preprocessor.py        Observation cleaning & validation
│   │   └── forecaster.py          Weighted mean & trend projection
│   ├── providers/
│   │   ├── base.py & factory.py   DemandDataProvider ABC & factory
│   │   ├── mock_provider.py       Deterministic mock provider
│   │   └── prometheus_provider.py Opt-in Prometheus time-series provider
│   └── services/
│       └── forecaster.py          DemandForecastingService
└── tests/
    ├── test_health.py
    ├── test_demand_api.py
    ├── test_contract_conformance.py
    ├── test_data_quality.py
    ├── test_demand_observations.py
    ├── test_error_handling.py
    ├── test_forecasting_engine.py
    ├── test_mock_provider.py
    ├── test_preprocessor.py
    ├── test_prometheus_provider.py
    └── test_traceability.py
```

---

## API Endpoints

### `POST /api/v1/demand/forecast`

**Request**:
```json
{
  "forecast_horizon_seconds": 300,
  "target_service": "demo-api",
  "trace_id": "f6-steady-001",
  "historical_window_seconds": 3600,
  "observations": [
    {"timestamp": 1757070000.0, "rps": 50.0},
    {"timestamp": 1757070030.0, "rps": 52.0}
  ]
}
```

**Response**:
```json
{
  "event_id": "e89c1d04-4fa2-47b8-bc81-abcdef012345",
  "trace_id": "f6-steady-001",
  "generated_at": "2026-09-05T12:00:00Z",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "model_version": "demand-v1",
  "forecast_horizon_seconds": 300,
  "predicted_legitimate_rps": 54.9,
  "lower_bound_rps": 0.0,
  "upper_bound_rps": 474.9,
  "confidence": 0.28
}
```

---

## Configuration (`app/config/settings.py`)

| Setting | Default | Description |
| :--- | :--- | :--- |
| `SERVICE_NAME` | `demand-intelligence` | Service identifier |
| `SERVICE_VERSION` | `0.1.0` | Service version |
| `CONTRACT_VERSION` | `1.0.0` | Contract schema version |
| `MODEL_VERSION` | `demand-v1` | Forecasting engine version |
| `PORT` | `8002` | Listen port |
| `FORECAST_MIN_OBSERVATIONS` | `2` | Minimum samples required for forecast |
| `FORECAST_MIN_OBSERVATIONS_FOR_TREND` | `5` | Minimum samples required for trend slope |
| `FORECAST_RECENCY_WEIGHT_DECAY` | `0.85` | Exponential decay factor |

---

## Tests (100 passing)

Run isolated tests:
```powershell
$env:PYTHONPATH="$PWD\services\demand-intelligence"; python -m pytest services/demand-intelligence/tests -v
```
