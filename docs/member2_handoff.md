# SentinelScale — Member 2 → Member 3 Handoff Document
# Demand Intelligence — Checkpoint 3 Integration Readiness

**Date:** 2024 (branch: `member2/demand-intelligence`)  
**Contract version:** `1.0.0` (frozen)  
**Status: ✅ INTEGRATION READY**

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
> If `observations` is omitted, the service uses the internal `MockDemandProvider`.

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
74 passed, 0 failed
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
- [x] 74 tests passing

**All criteria met. Member 3 can now replace `FakeDemandForecast` with the real service.**
