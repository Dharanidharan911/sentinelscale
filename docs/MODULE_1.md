# Module 1 — Traffic Intelligence

> Service directory: `services/traffic-intelligence/`
> Port: `8001`
> Owner branch: `member1/traffic-intelligence`
> Last updated: 2026-09-05

---

## Responsibility

Module 1 evaluates incoming API traffic telemetry and outputs a structured security risk assessment. It answers: *"Is the current traffic legitimate, suspicious, or malicious, and what proportion represents genuine business demand?"*

Output: `TrafficAssessment` consumed by Module 3 (Platform & Decision Engine) and the F2 Demand Observation Accumulator.

---

## Implementation State: `traffic-rules-v1`

Module 1 implements rule-based behavioral anomaly detection and risk scoring in `app/pipeline/`.

### File Structure

```
services/traffic-intelligence/
├── Dockerfile
├── requirements.txt
├── app/
│   ├── main.py                    FastAPI application factory
│   ├── logging.py                 StructuredLoggingMiddleware
│   ├── api/v1/endpoints.py        FastAPI routes
│   ├── config/settings.py         pydantic-settings config
│   ├── models/
│   │   └── traffic.py             TrafficAssessment, AssessmentRequest, TrafficClassification, TrafficTelemetryInput
│   ├── mock/
│   │   └── generator.py           MockTrafficDataGenerator (fallback)
│   ├── pipeline/
│   │   ├── aggregator.py          Telemetry feature extraction
│   │   ├── classifier.py          Classification & risk heuristics
│   │   └── assessor.py            Pipeline assessment logic
│   └── services/
│       └── assessor.py            TrafficAssessmentService
└── tests/
    ├── test_health.py
    ├── test_traffic_api.py
    ├── test_contract_conformance.py
    ├── test_pipeline.py
    └── test_scenarios.py
```

---

## Behavioral Risk Assessment Rules

The pipeline analyzes:
1. **Burstiness Ratio**: Current RPS relative to baseline expected RPS.
2. **Client IP Concentration**: Proportion of traffic originating from the top client IP.
3. **User-Agent Anomalies**: Proportion of bot, script, empty, or abnormal User-Agents.
4. **Error Rate**: Ratio of 4xx/5xx responses to total requests.
5. **Endpoint Focus**: Concentration of requests on a single endpoint.

### Classification Thresholds
- **`LEGITIMATE`**: `risk_score < 0.50` and `legitimacy_score >= 0.65`
- **`SUSPICIOUS`**: `0.50 <= risk_score < 0.80`
- **`MALICIOUS`**: `risk_score >= 0.80`

---

## API Endpoints

### `POST /api/v1/traffic/assess`

**Request**:
```json
{
  "window_seconds": 60,
  "target_service": "demo-api",
  "trace_id": "f6-steady-001",
  "telemetry": {
    "total_requests": 50,
    "total_rps": 50.0,
    "baseline_rps": 50.0,
    "top_ip_ratio": 0.08,
    "non_standard_ua_ratio": 0.0
  }
}
```

**Response**:
```json
{
  "event_id": "c1f7b0f2-53b9-4f24-8b63-123456789abc",
  "trace_id": "f6-steady-001",
  "timestamp": "2026-09-05T12:00:00Z",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "model_version": "traffic-rules-v1",
  "window_seconds": 60,
  "total_rps": 50.0,
  "legitimate_rps_estimate": 50.0,
  "suspicious_rps_estimate": 0.0,
  "risk_score": 0.05,
  "legitimacy_score": 0.95,
  "confidence": 0.51,
  "classification": "legitimate",
  "top_signals": ["low_ip_concentration", "standard_user_agents"]
}
```

---

## Configuration (`app/config/settings.py`)

| Setting | Default | Description |
| :--- | :--- | :--- |
| `SERVICE_NAME` | `traffic-intelligence` | Service identifier |
| `SERVICE_VERSION` | `0.1.0` | Service version |
| `CONTRACT_VERSION` | `1.0.0` | Contract schema version |
| `MODEL_VERSION` | `traffic-rules-v1` | Rule engine version |
| `PORT` | `8001` | Listen port |

---

## Tests (5 passing)

Run isolated tests:
```powershell
$env:PYTHONPATH="$PWD\services\traffic-intelligence"; python -m pytest services/traffic-intelligence/tests -v
```
