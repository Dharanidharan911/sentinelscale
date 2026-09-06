# SentinelScale — Member 2 → Member 3 Handoff Document
# Demand Intelligence — Checkpoint 3 Integration Readiness

**Date:** 2026-09-05 (branch: `member2/demand-intelligence`)
**Contract version:** `1.0.0` (frozen)  
**Status: ✅ MEMBER 2 FEATURE-COMPLETE; INTEGRATION READY**

---

## 1. Service Identity

| Field | Value |
|---|---|
| Service | `demand-intelligence` |
| Branch | `member2/demand-intelligence` |
| Service version | `0.1.0` |
| Contract version | `1.0.0` |
| Model version | `demand-v1` |
| Service directory | `services/demand-intelligence/` |
| Current local commit | `9bd5bf4` |
| Current local tag | `member2-v1.5-confidence-observability` |
| Remote publishing | Not authorized; nothing in v1.3–v1.5 was pushed |

---

## 2. Endpoint Specification

### Forecast Endpoint

```
POST /api/v1/demand/forecast
Content-Type: application/json
X-Trace-ID: <optional-trace-id>
```

### Minimum Request (uses internal mock provider)

```json
{
  "forecast_horizon_seconds": 300
}
```

### Full Request with Inline Observations (recommended for integration)

```json
{
  "forecast_horizon_seconds": 300,
  "target_service": "demo-api",
  "trace_id": "upstream-trace-id-from-member3",
  "historical_window_seconds": 3600,
  "observations": [
    {"timestamp": 1700000000.0, "rps": 850.0},
    {"timestamp": 1700000030.0, "rps": 870.0},
    {"timestamp": 1700000060.0, "rps": 830.0},
    {"timestamp": 1700000090.0, "rps": 855.0},
    {"timestamp": 1700000120.0, "rps": 842.0}
  ]
}
```

> **Note:** Member 3 should supply `observations` from its telemetry/resource layer.  
> If omitted, the service uses `PrometheusDemandProvider` only when `PROMETHEUS_URL` is configured; otherwise it uses the deterministic `MockDemandProvider`.

---

## 3. Response Example (DemandForecast v1.0.0)

```json
{
  "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "trace_id": "upstream-trace-id-from-member3",
  "generated_at": "2024-01-15T10:30:00.123456+00:00",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "model_version": "demand-v1",
  "forecast_horizon_seconds": 300,
  "predicted_legitimate_rps": 851.4231,
  "lower_bound_rps": 714.8812,
  "upper_bound_rps": 988.0,
  "confidence": 0.8431
}
```

---

## 4. Field Semantics

| Field | Type | Semantics |
|---|---|---|
| `event_id` | UUID string | Unique per forecast call. Use for log correlation. |
| `trace_id` | string | Propagated from request body (priority) or `X-Trace-ID` header. Auto-generated if absent. |
| `generated_at` | ISO-8601 datetime | UTC timestamp of forecast generation. |
| `contract_version` | semver string | Always `"1.0.0"`. Frozen. |
| `service_version` | string | Demand Intelligence service version. |
| `model_version` | string | `"demand-v1"` — RWMA deterministic baseline. |
| `forecast_horizon_seconds` | integer ≥ 1 | Echoes the request's horizon. |
| `predicted_legitimate_rps` | float ≥ 0 | Point estimate of legitimate RPS at `now + horizon`. |
| `lower_bound_rps` | float ≥ 0 | Lower bound of prediction interval (≤ predicted). |
| `upper_bound_rps` | float ≥ 0 | Upper bound of prediction interval (≥ predicted). |
| `confidence` | float [0.0, 1.0] | Forecast confidence. See confidence semantics below. |

### Confidence Semantics

| Range | Recommended Decision Engine Behaviour |
|---|---|
| `≥ 0.85` | High confidence — act on forecast directly |
| `0.5–0.85` | Moderate confidence — apply scaling with normal guardrails |
| `0.3–0.5` | Low confidence — prefer `HOLD`, apply conservative guardrails |
| `< 0.3` | Very low confidence — `HOLD`; do not scale based on this forecast |

---

## 5. Trace ID Behaviour

- If `trace_id` is in the request body → **that value is used verbatim**
- Else if `X-Trace-ID` header is present → **header value is used**
- Else → **auto-generated**: `"trace-{16-char hex}"` (e.g. `"trace-a3f1b9c2d4e5f601"`)

The `X-Trace-ID` header is also echoed in the response headers.

---

## 6. Error Semantics

| HTTP Status | `error` key | Meaning | Member 3 Action |
|---|---|---|---|
| `422` | `insufficient_data` | < 2 valid observations available | Log and `HOLD` — this is a data gap, not zero demand |
| `422` | `invalid_observation` | Negative RPS or invalid data | Log; inspect observation pipeline |
| `503` | `provider_unavailable` | Internal provider down | Retry with backoff; `HOLD` if persistent |
| `500` | `forecast_calculation_error` | Unexpected engine error | Alert; fall back to `HOLD` |

**CRITICAL:** A `422` or `503` from this service must **never** be interpreted as "zero legitimate demand." These are data/availability errors. The correct default is `HOLD`.

### Optional Prometheus Provider

Set `DEMAND_PROMETHEUS_URL` in Compose (mapped to service `PROMETHEUS_URL`) to use compatible request-rate telemetry. The default query is:

```promql
sum(rate(http_requests_total{service="{target_service}"}[1m]))
```

`{target_service}` is supplied from the request; override `PROMETHEUS_QUERY` for deployed metric names. Unreachable, malformed, or invalid telemetry returns the existing `503 provider_unavailable`; a successful empty query returns `422 insufficient_data`. Neither means zero RPS.

### Confidence and Diagnostics

Confidence is deterministic and combines sample count, demand variance, history
span relative to horizon, and sampling regularity. Valid irregular sampling
lowers confidence but remains forecastable. Service logs include the provider,
observation count, horizon, trace ID, and processing latency; none are added to
the frozen `DemandForecast` contract.

### Observation Validation

Inline and provider observations must use finite timestamp and RPS values. A
timestamp more than `OBSERVATION_MAX_FUTURE_SKEW_SECONDS` (default: 60) ahead
of the service clock is rejected as invalid telemetry. This is a `422` invalid
data condition, not a zero-demand signal; Member 3 should `HOLD` and inspect
the telemetry clock/source.

---

## 7. Health / Readiness Endpoints

```bash
GET /health   → {"status": "ok", "service": "demand-intelligence"}
GET /ready    → {"status": "ready", "service": "demand-intelligence"}
GET /version  → {"service": "demand-intelligence", "service_version": "0.1.0", 
                  "contract_version": "1.0.0", "model_version": "demand-v1", 
                  "environment": "development"}
```

---

## 8. Run Instructions

```bash
cd services/demand-intelligence
pip install -r requirements.txt
uvicorn app.main:app --port 8002 --reload
```

API docs: http://localhost:8002/docs  
OpenAPI spec: http://localhost:8002/openapi.json

---

## 9. Test Command and Results

```bash
# From repository root:
python -m pytest services/demand-intelligence/tests -v -o "pythonpath=services/demand-intelligence"
```

**Results:**
```
100 passed, 0 failed
```

Test coverage includes:
- Domain model validation
- Preprocessor: sorting, deduplication, invalid data rejection
- Forecasting engine: bounds invariant, confidence, trend detection, determinism
- Mock provider: ordering, determinism, non-negativity
- API: inline observations, trace propagation, validation, all contract fields
- Error handling: insufficient data (422), not silently zero
- Traceability: UUID validity, ISO-8601 timestamps, contract version

---

## 10. Files Changed / Added

### New Files

| File | Purpose |
|---|---|
| `app/models/demand.py` | Extended with `DemandObservation`; `ForecastRequest.observations` |
| `app/errors.py` | `InsufficientDataError`, `InvalidObservationError`, etc. |
| `app/providers/__init__.py` | Package |
| `app/providers/base.py` | Abstract `DemandProvider` interface |
| `app/providers/mock_provider.py` | Deterministic sinusoidal mock |
| `app/providers/static_provider.py` | Wraps inline observations as provider |
| `app/engine/__init__.py` | Package |
| `app/engine/preprocessor.py` | Validate, sort, deduplicate, statistics |
| `app/engine/forecaster.py` | RWMA + trend + confidence + DemandForecast builder |
| `tests/test_demand_observations.py` | Domain model tests |
| `tests/test_preprocessor.py` | Preprocessor unit tests |
| `tests/test_forecasting_engine.py` | Engine unit tests |
| `tests/test_mock_provider.py` | Provider tests |
| `tests/test_error_handling.py` | Error handling integration tests |
| `tests/test_traceability.py` | Trace ID / metadata tests |
| `README.md` | Service documentation |

### Modified Files

| File | Change |
|---|---|
| `app/services/forecaster.py` | Full rewrite: provider selection + engine orchestration |
| `app/api/v1/endpoints.py` | Full rewrite: structured error mapping |
| `tests/test_demand_api.py` | Extended with 9 tests |

### Unchanged Files (preserved)

| File | Status |
|---|---|
| `app/main.py` | Unchanged |
| `app/config/settings.py` | Unchanged |
| `app/logging.py` | Unchanged |
| `app/mock/generator.py` | Preserved (no longer used in production path) |
| `contracts/demand/demand_forecast.schema.json` | **Frozen — not touched** |

---

## 11. Known Limitations

| Limitation | Severity | Future Work |
|---|---|---|
| Default provider is `MockDemandProvider` | Low — acceptable for M3 integration | Wire Prometheus provider in Phase 19 |
| No seasonality / cyclic patterns | Low | Phase 2 model upgrade |
| No persistence between requests | Low | Stateful rolling window (future) |
| `demand-v1` is deterministic linear only | Low | ML model upgrade later |
| Confidence is a heuristic estimate | Low — bounded and meaningful | Calibrate with real data |

---

## 12. Suggested Member 3 Adapter (DemandForecastClient)

```python
import httpx
from typing import Optional, List

DEMAND_SERVICE_URL = "http://demand-intelligence:8002"

async def get_demand_forecast(
    horizon_seconds: int = 300,
    observations: Optional[List[dict]] = None,
    trace_id: Optional[str] = None,
) -> dict:
    payload = {"forecast_horizon_seconds": horizon_seconds}
    if observations:
        payload["observations"] = observations
    if trace_id:
        payload["trace_id"] = trace_id

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{DEMAND_SERVICE_URL}/api/v1/demand/forecast",
            json=payload,
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json()  # → DemandForecast dict
```

The response dict maps directly to the frozen `DemandForecast` domain model.

---

## 13. Member 3 Integration Checkpoint Criteria (Checkpoint 3)

Member 3 can proceed with real `DemandForecast` integration once:

- [x] `/health` returns `{"status": "ok"}`
- [x] `/ready` returns `{"status": "ready"}`
- [x] `POST /api/v1/demand/forecast` returns valid `DemandForecast`
- [x] `predicted_legitimate_rps` is populated
- [x] `confidence` is populated
- [x] `trace_id` propagates from request
- [x] `contract_version` is `"1.0.0"`
- [x] JSON Schema validation passes
- [x] 100 tests passing

**All Member 2 criteria are met. Member 3 can replace `FakeDemandForecast` with the real service.**

---

## 14. Integration Boundary and Final Readiness

Member 2 consumes `DemandObservation` records (inline, mock, or provider
supplied) and produces only the frozen `DemandForecast` v1.0.0 contract.
Member 2 imports neither Member 1 nor Member 3 implementation internals.

```
TrafficAssessment v1.0.0
  -> [future contract-level observation/sanitization boundary]
  -> DemandObservation -> Demand Intelligence -> DemandForecast v1.0.0
  -> Member 3 DemandForecastClient -> DecisionContext
```

`TrafficAssessment` already exposes `legitimate_rps_estimate` and
`legitimacy_score`, but no repository-approved mapping from those assessments
to historical `DemandObservation` records exists. Member 1 and Member 3 must
agree that mapping at the contract/API boundary before wiring it; Member 2 must
not infer it or import either module's internals.

Prometheus is optional and requires a deployment metric/query configuration;
repository services do not emit the default `http_requests_total` metric. The
mock provider remains deterministic for tests and local integration.

Exact next integration action: have Member 3 call
`POST /api/v1/demand/forecast` with its contract-approved historical
`DemandObservation` list and propagate the shared trace ID.

---

## 15. IC-4 Model & Feature Architecture Update (2026-09-06)

- **Service Status**: 121 tests passing (100% pass rate).
- **Feature Engineering Layer (M2-4)**: `app/engine/features.py` extracts 12 deterministic, leakage-safe features (`recent_demand`, `lag_1`, `lag_2`, `rolling_mean_short`, `rolling_mean_full`, `rolling_std_full`, `trend_slope`, `rate_of_change`, `acceleration`, `sampling_regularity`, `time_span_seconds`, `horizon_ratio`).
- **ML Candidate Forecaster (M2-5)**: `app/engine/ml_forecaster.py` implements regularized Ridge regression (`demand-ml-v1`) with fallback to baseline `demand-v1` when $N < 4$.
- **Model Benchmark (M2-6)**: `benchmarks/benchmark_suite.py` executed across 6 synthetic scenarios. Baseline (`demand-v1`) achieved 54.19 RPS MAE and 83.3% interval coverage vs ML candidate (`demand-ml-v1`) 180.43 RPS MAE and 33.3% coverage due to surge-damping properties. Baseline retained as preferred default.
- **Provider & Engine Selection (M2-7)**: Configurable via `FORECAST_MODEL=baseline` (or `ml`) and `ML_RIDGE_ALPHA=1.0`. All outputs continue to conform 100% to frozen `DemandForecast` v1.0.0.

---

## 16. Milestones M2-8 Through M2-14 Completion & Hardening (2026-09-06)

- **Test Suite Status**: **159 tests passing (100% pass rate)**. Full microservices runner `python run_tests.py` passes all 4 suites.
- **M2-8 (DemandForecast Integration)**: Verified complete end-to-end integration via client flow simulation. Zero-RPS demand is verified as physically valid legitimate workload (never treated as missing). Full conformance against `contracts/demand/demand_forecast.schema.json` v1.0.0.
- **M2-9 (Prediction Intervals)**: Implemented horizon-dilated and cadence-dilated uncertainty:
  $\sigma_{\text{eff}} = \sigma \sqrt{1 + h / \max(T, 30)} \times (1 + 0.5(1 - \text{regularity}))$.
  Strictly satisfies invariant $0.0 \le \text{lower} \le \text{predicted} \le \text{upper}$. Improved ML candidate benchmark interval coverage from 33.3% to 66.7%.
- **M2-10 (Confidence Calibration)**: Multi-factor confidence score calibrated with data quality, sample count, relative variance (CV), horizon ratio, and cadence regularity. Monotonically penalizes sparse, volatile, or stale data.
- **M2-11 (Failure / Fallback Handling)**: Strict explicit failure semantics. Invariant: errors NEVER emit silent 0.0 RPS. Provider outages return HTTP 503; invalid data returns HTTP 422. ML candidate numerical anomalies (singular matrix, non-finite output) fallback transparently to baseline `demand-v1`.
- **M2-12 (Data Quality Intelligence)**: Implemented `app/engine/data_quality.py` (`DataQualityAssessor`). Evaluates completeness ratio, cadence regularity, staleness, noise-to-signal ratio, and categorical quality rating (`EXCELLENT`, `GOOD`, `DEGRADED`, `POOR`).
- **M2-13 (Seasonality Engine)**: Implemented `app/engine/seasonality.py` (`SeasonalityDetector`). Evaluates autocorrelation peaks with dynamic white-noise significance ($r \ge \max(0.35, 1.96 / \sqrt{N})$) and Fourier harmonic regression. Requires $\ge 2$ full periods before confirming seasonality; falls back cleanly to non-seasonal RWMA projection if periodicity is unconfirmed.
- **M2-14 (Explainability Engine)**: Implemented `app/engine/explainability.py` (`ForecastExplainer`). Synthesizes deterministic reason tags (`MODEL_*`, `QUALITY_*`, `TREND_*`, `VOLATILITY_*`, `SEASONALITY_*`, `UNCERTAINTY_*`). Surfaces tags through HTTP response headers (`X-Forecast-Explanation`, `X-Forecast-Quality`) and structured JSON logs without altering the frozen JSON Schema v1.0.0.


