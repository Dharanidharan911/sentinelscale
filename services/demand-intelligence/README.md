# Demand Intelligence Service — README

**SentinelScale Module 2**

> Predicts future legitimate API workload demand so that Member 3 (Platform) can make informed, security-aware scaling decisions.

---

## What This Service Does

The Demand Intelligence service receives demand observations (historical RPS readings) and returns a `DemandForecast` — a contract-versioned prediction of legitimate requests per second over a configurable future horizon.

It does **not**:
- Make scaling decisions
- Query Kubernetes
- Control traffic or rate-limiting
- Import Member 3 internals

---

## API

### Health / Readiness

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Liveness check |
| `/ready` | GET | Readiness check |
| `/version` | GET | Service and contract version info |

### Forecast

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/demand/forecast` | POST | Generate a `DemandForecast` |

#### Request Body (`ForecastRequest`)

```json
{
  "forecast_horizon_seconds": 300,
  "target_service": "demo-api",
  "trace_id": "optional-upstream-trace-id",
  "historical_window_seconds": 3600,
  "observations": [
    {"timestamp": 1700000000.0, "rps": 850.0},
    {"timestamp": 1700000030.0, "rps": 870.0}
  ]
}
```

- `forecast_horizon_seconds` — required (default: 300). How far forward to forecast.
- `observations` — optional. If omitted, the service uses `PrometheusDemandProvider` when configured, otherwise the internal `MockDemandProvider`.
  If provided, must contain **≥ 2** valid observations.
- `trace_id` — optional. Propagated to forecast output. Falls back to `X-Trace-ID` header.

#### Response (`DemandForecast` — contract v1.0.0)

```json
{
  "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "trace_id": "optional-upstream-trace-id",
  "generated_at": "2024-01-15T10:30:00.123456+00:00",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "model_version": "demand-v1",
  "forecast_horizon_seconds": 300,
  "predicted_legitimate_rps": 857.3142,
  "lower_bound_rps": 724.8812,
  "upper_bound_rps": 989.7472,
  "confidence": 0.8431
}
```

#### Error Responses

| Status | `error` field | Meaning |
|---|---|---|
| `422` | `insufficient_data` | Fewer than 2 valid observations provided. NOT zero demand — this is a data availability error. |
| `422` | `invalid_observation` | Observation contains impossible values (e.g. negative RPS). |
| `503` | `provider_unavailable` | Internal demand provider unreachable. |
| `500` | `forecast_calculation_error` | Unexpected error in forecasting engine. |

---

## Architecture

```
ForecastRequest
    │
    ▼
DemandForecastingService      ← selects provider
    │
    ├── StaticObservationProvider  ← if request.observations provided
    ├── PrometheusDemandProvider   ← opt-in telemetry adapter
    └── MockDemandProvider         ← fallback when Prometheus is unconfigured
    │
    ▼
Preprocessor                   ← validates, sorts, deduplicates
    │
    ▼
Forecasting Engine             ← RWMA + linear trend + confidence scoring
    │
    ▼
DemandForecast (v1.0.0)
```

### Forecasting Algorithm

**Model**: `demand-v1` — Recency-Weighted Moving Average + Linear Trend Projection

1. **Validate & preprocess** observations (sort, deduplicate, reject invalid)
2. **Weighted mean** — most recent observations weighted heavier (`decay=0.85`)
3. **Trend detection** — linear regression slope over cleaned series
4. **Trend projection** — if ≥ 5 observations, extrapolate trend over `forecast_horizon_seconds`
5. **Prediction interval** — ±1.5 × historical std-dev around point estimate
6. **Confidence** — based on sample count and coefficient of variation

### Confidence Semantics

| Confidence | Meaning |
|---|---|
| `≥ 0.85` | High confidence — strong historical signal, low variance |
| `0.5–0.85` | Moderate confidence — reasonable signal |
| `< 0.5` | Low confidence — sparse data or high variance |
| `< 0.3` | Very low — Member 3 should consider `HOLD` |

---

## Running Locally

```bash
cd services/demand-intelligence
pip install -r requirements.txt
uvicorn app.main:app --port 8002 --reload
```

Service docs: http://localhost:8002/docs

### Prometheus Demand Provider

Set `DEMAND_PROMETHEUS_URL` with Docker Compose (or `PROMETHEUS_URL` when
running directly) to enable the real telemetry provider. It calls
`/api/v1/query_range` with a five-second default timeout. `PROMETHEUS_QUERY`
may override the default query and may contain `{target_service}`.

```env
DEMAND_PROMETHEUS_URL=http://prometheus:9090
DEMAND_PROMETHEUS_QUERY=sum(rate(http_requests_total{service="{target_service}"}[1m]))
PROMETHEUS_STEP_SECONDS=30
PROMETHEUS_TIMEOUT_SECONDS=5
```

The query must return RPS matrix samples. An empty successful response is no
data and yields the existing insufficient-data error; unreachable or malformed
telemetry yields `503 provider_unavailable`, never a zero-demand forecast.

### Observation Quality Rules

Observations must have finite, positive Unix timestamps and finite,
non-negative RPS values. Timestamps more than 60 seconds ahead of the service
clock are rejected by default; configure `OBSERVATION_MAX_FUTURE_SKEW_SECONDS`
when telemetry producers have a known clock offset. These failures are invalid
data, not legitimate zero demand.

---

## Running Tests

```bash
# From repository root:
python -m pytest services/demand-intelligence/tests -v -o "pythonpath=services/demand-intelligence"
```

**Expected result:** 74 tests passing, 0 failing.

---

## Contract

- **Contract file**: `contracts/demand/demand_forecast.schema.json`  
- **Contract version**: `1.0.0` (frozen — do not modify without team agreement)
- **Schema validation**: `test_contract_conformance.py` validates every forecast response against the JSON Schema

---

## Known Limitations

| Limitation | Impact |
|---|---|
| Default query metric is not yet emitted by repository services | Configure a query matching deployed telemetry before enabling Prometheus |
| Linear trend model | Does not capture seasonality, non-linear patterns |
| No persistence | History lives only within the request; no database |

---

## Integration for Member 3

Call `POST /api/v1/demand/forecast` from your `DemandForecastClient`.

**Minimum viable call** (uses internal mock provider):
```json
{"forecast_horizon_seconds": 300}
```

**With real observations** (supply from telemetry adapter):
```json
{
  "forecast_horizon_seconds": 300,
  "trace_id": "<your-trace-id>",
  "observations": [
    {"timestamp": 1700000000.0, "rps": 850.0},
    ...
  ]
}
```

The `DemandForecast` response is the contract input to `DecisionContext`.
