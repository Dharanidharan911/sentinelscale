# Module 1 — Traffic Intelligence

> Service directory: `services/traffic-intelligence/`
> Port: `8001`
> Owner branch: `member1/traffic-intelligence`
> Last updated: 2026-09-01

---

## Responsibility

Module 1 evaluates incoming API traffic telemetry and outputs a structured security risk assessment. It answers: *"Is the current traffic legitimate, suspicious, or malicious?"*

Output: `TrafficAssessment` consumed by Module 3 (Platform & Decision Engine) to inform scaling decisions.

---

## Current Implementation State: Mock (traffic-v0)

All intelligence is currently backed by a deterministic mock generator in `app/mock/generator.py`. The mock is tagged `traffic-v0 (mock)` and returns fixed values.

### File Structure

```
services/traffic-intelligence/
├── Dockerfile
├── requirements.txt               (fastapi, uvicorn, pydantic, httpx, pytest, jsonschema)
├── app/
│   ├── main.py                    FastAPI application factory
│   ├── logging.py                 StructuredLoggingMiddleware
│   ├── api/v1/endpoints.py        FastAPI routes
│   ├── config/settings.py         pydantic-settings config
│   ├── models/
│   │   └── traffic.py             TrafficAssessment, AssessmentRequest, TrafficClassification
│   ├── mock/
│   │   └── generator.py           MockTrafficDataGenerator
│   └── services/
│       └── assessor.py            TrafficAssessmentService
└── tests/
    ├── test_health.py
    ├── test_traffic_api.py
    └── test_contract_conformance.py
```

---

## API Endpoints

### `POST /api/v1/traffic/assess`

**Request**:
```json
{"window_seconds": 60, "target_service": "demo-api", "trace_id": "optional"}
```

**Response** (TrafficAssessment — always these fixed values in mock):
```json
{
  "event_id": "<uuid>",
  "trace_id": "...",
  "timestamp": "...",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "model_version": "traffic-v0 (mock)",
  "window_seconds": 60,
  "total_rps": 2500.0,
  "legitimate_rps_estimate": 850.0,
  "suspicious_rps_estimate": 1650.0,
  "risk_score": 0.84,
  "legitimacy_score": 0.34,
  "confidence": 0.91,
  "classification": "suspicious",
  "top_signals": ["high_burst_rate", "client_ip_concentration", "non_standard_user_agent"]
}
```

### `GET /health`, `GET /ready`, `GET /version`

Standard system health endpoints.

---

## Data Models

### `TrafficClassification` (Enum)
```python
class TrafficClassification(str, Enum):
    LEGITIMATE = "legitimate"
    SUSPICIOUS = "suspicious"
    MALICIOUS = "malicious"
    UNKNOWN = "unknown"
```

### `TrafficAssessment` (Pydantic Model)
All scores are validated floats in `[0.0, 1.0]`. `top_signals` is `List[str]`.

### `AssessmentRequest` (Pydantic Model)
Accepts `window_seconds` (int, ≥1, default 60), `target_service` (str, default "demo-api"), `trace_id` (optional str).

---

## Service Layer

```python
class TrafficAssessmentService:
    def __init__(self):
        self.mock_generator = MockTrafficDataGenerator()

    async def assess_traffic(self, request: AssessmentRequest) -> TrafficAssessment:
        return self.mock_generator.generate_assessment(
            window_seconds=request.window_seconds,
            trace_id=request.trace_id
        )
```

The `window_seconds` parameter is passed through but not used by the mock — it always returns the same values regardless.

---

## Mock Generator

`MockTrafficDataGenerator.generate_assessment()` returns a deterministic `TrafficAssessment` with:
- `total_rps=2500.0`
- `legitimate_rps_estimate=850.0`
- `suspicious_rps_estimate=1650.0`
- `risk_score=0.84`
- `legitimacy_score=0.34`
- `confidence=0.91`
- `classification=TrafficClassification.SUSPICIOUS`
- `top_signals=["high_burst_rate", "client_ip_concentration", "non_standard_user_agent"]`

A new `event_id` (UUID) and `trace_id` are generated per call.

---

## JSON Schema Contract

**File**: `contracts/traffic/traffic_assessment.schema.json`

This schema is validated in `tests/test_contract_conformance.py` on every test run. Do not change the schema without a version bump and team review.

---

## Configuration (`app/config/settings.py`)

| Setting | Default | Description |
| :--- | :--- | :--- |
| `SERVICE_NAME` | `traffic-intelligence` | Service identifier |
| `SERVICE_VERSION` | `0.1.0` | Service version |
| `CONTRACT_VERSION` | `1.0.0` | Contract schema version |
| `MODEL_VERSION` | `traffic-v0` | Model/heuristic version |
| `ENVIRONMENT` | `development` | Runtime environment |
| `LOG_LEVEL` | `INFO` | Logging level |
| `PORT` | `8001` | Listen port |

---

## Tests (5 passing)

| Test file | Coverage |
| :--- | :--- |
| `test_health.py` | `/health` endpoint returns 200 OK |
| `test_traffic_api.py` | `POST /api/v1/traffic/assess` returns valid TrafficAssessment |
| `test_contract_conformance.py` | Mock output validates against JSON Schema |

Run: `$env:PYTHONPATH="$PWD\services\traffic-intelligence"; python -m pytest services/traffic-intelligence/tests -v`

---

## Future Implementation (Not Yet Coded)

When Module 1 is upgraded from mock to real intelligence:

1. **Telemetry ingestion**: Pull from Prometheus — request rates per endpoint, status code distributions, header patterns, client IP distributions
2. **Feature extraction**: Burstiness coefficient, IP entropy (Shannon), user-agent entropy, endpoint dispersion ratio, payload size distribution
3. **ML model**: Replace `MockTrafficDataGenerator` in `assessor.py` with real model inference (XGBoost or Isolation Forest)
4. **Explainability**: `top_signals` should reflect real computed signal names
5. **Model versioning**: Update `MODEL_VERSION` setting (e.g., `traffic-v1`) and tag in contract payload

**Invariants that must be preserved when implementing real Module 1**:
- Must return a valid `TrafficAssessment` matching `contracts/traffic/traffic_assessment.schema.json`
- `risk_score`, `legitimacy_score`, `confidence` must remain in `[0.0, 1.0]`
- `classification` must remain in `{legitimate, suspicious, malicious, unknown}`
- Mock fallback must be preserved in `app/mock/generator.py`
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
