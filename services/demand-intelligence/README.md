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

### Forecasting Engines

#### 1. Baseline Engine (`demand-v1` — Default)
Recency-Weighted Moving Average + Linear Trend Projection:
1. **Validate & preprocess** observations (sort, deduplicate, reject invalid)
2. **Weighted mean** — most recent observations weighted heavier (`decay=0.85`)
3. **Trend detection** — linear regression slope over cleaned series
4. **Trend projection** — if ≥ 5 observations, extrapolate trend over `forecast_horizon_seconds` (capped to prevent runaway extrapolation)
5. **Prediction interval** — ±1.5 × historical std-dev around point estimate
6. **Confidence** — based on sample count, variance, horizon ratio, and sampling regularity

#### 2. ML Candidate Engine (`demand-ml-v1` — Configurable Opt-In)
Feature-Engineered Regularized Ridge Linear Regression:
1. **Feature Engineering (M2-4)**: `app/engine/features.py` extracts 12 deterministic, leakage-safe features (`recent_demand`, lags 1–2, short/full rolling statistics, trend slope, rate of change, acceleration, cadence regularity, horizon ratio).
2. **Ridge Forecaster (M2-5)**: `app/engine/ml_forecaster.py` fits local autoregressive dynamics via closed-form Ridge estimator ($\alpha = 1.0$).
3. **Fallback Safety**: If observations are fewer than 4 or if numerical anomalies occur, gracefully falls back to baseline `demand-v1`.
4. **Configuration (M2-7)**: Activated via `FORECAST_MODEL=ml` or `FORECAST_MODEL=demand-ml-v1`.

### 3. Data Quality, Seasonality & Explainability (M2-8 through M2-14)
- **Data Quality Intelligence (M2-12)**: `app/engine/data_quality.py` analyzes observation completeness, sampling cadence regularity, staleness, and noise-to-signal ratio to assign continuous scores and categorical ratings (`EXCELLENT`, `GOOD`, `DEGRADED`, `POOR`).
- **Seasonality Engine (M2-13)**: `app/engine/seasonality.py` detects cyclical patterns via autocorrelation peak analysis and Fourier harmonic regression when observation history covers at least 2 full periods. Falls back cleanly to non-seasonal RWMA projection when cycles are unconfirmed.
- **Horizon & Regularity Dilated Prediction Intervals (M2-9)**: Evaluates dynamic interval expansion ($\sigma \sqrt{1 + h / \max(T, 30)}$) with cadence jitter dilation, strictly preserving $0 \le \text{lower} \le \text{predicted} \le \text{upper}$.
- **Calibrated Confidence Scoring (M2-10)**: Multi-factor confidence score calibrated against sample scarcity, CV, horizon ratio, cadence irregularity, and data quality.
- **Explicit Failure & Fallback Handling (M2-11)**: Strict error semantics (422 for insufficient data, 503 for provider outages). ML candidate numerical anomalies transparently fall back to baseline `demand-v1`. Errors never emit silent 0.0 RPS.
- **Forecast Explainability (M2-14)**: `app/engine/explainability.py` synthesizes deterministic reason tags (`MODEL_*`, `QUALITY_*`, `TREND_*`, `VOLATILITY_*`, `SEASONALITY_*`, `UNCERTAINTY_*`) attached to HTTP response headers (`X-Forecast-Explanation`, `X-Forecast-Quality`) and structured JSON logs without altering frozen contract v1.0.0.

### Confidence Semantics

| Confidence | Meaning |
|---|---|
| `≥ 0.85` | High confidence — strong historical signal, low variance, fresh telemetry |
| `0.5–0.85` | Moderate confidence — reasonable signal |
| `< 0.5` | Low confidence — sparse data, high variance, or long horizon |
| `< 0.3` | Very low — Member 3 should consider `HOLD` |

---

## Running Locally

```bash
cd services/demand-intelligence
pip install -r requirements.txt
uvicorn app.main:app --port 8002 --reload
```

Service docs: http://localhost:8002/docs

### Model & Telemetry Configuration

```env
# Engine selection: "baseline" (demand-v1, default) or "ml" (demand-ml-v1)
FORECAST_MODEL=baseline
ML_RIDGE_ALPHA=1.0

# Optional Prometheus provider
DEMAND_PROMETHEUS_URL=http://prometheus:9090
DEMAND_PROMETHEUS_QUERY=sum(rate(http_requests_total{service="{target_service}"}[1m]))
PROMETHEUS_STEP_SECONDS=30
PROMETHEUS_TIMEOUT_SECONDS=5
```

---

## Running Benchmarks (M2-6)

Run the reproducible benchmark suite comparing baseline vs ML candidate:

```bash
# From services/demand-intelligence/ or root:
python -m benchmarks.benchmark_suite
```

Findings: Baseline (`demand-v1`) achieved 54.71 RPS MAE and 83.3% interval coverage vs ML candidate (`demand-ml-v1`) 180.43 RPS MAE and 66.7% coverage across 6 synthetic scenarios. Baseline remains the production default. Full report in `benchmarks/BENCHMARK_REPORT.md`.

---

## Running Tests

```bash
# From repository root:
python -m pytest services/demand-intelligence/tests -v -o "pythonpath=services/demand-intelligence"
```

**Expected result:** 159 tests passing, 0 failing.

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
| Stateful persistence | History lives within the request or telemetry query; no internal database |

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
