# API Contracts — SentinelScale

> Last updated: 2026-09-01
> Canonical JSON Schema files: `contracts/`

> [!IMPORTANT]
> Contracts are public interfaces. No silent modifications. Any breaking change requires a version bump and team review. See `CONTRACTS.md` for versioning rules.

---

## Contract 1: Traffic Assessment

**Schema file**: `contracts/traffic/traffic_assessment.schema.json`
**Endpoint**: `POST /api/v1/traffic/assess` (Traffic Intelligence service, port 8001)
**Producer**: Module 1 — Traffic Intelligence (`services/traffic-intelligence/`)
**Consumer**: Module 3 — Platform (via `app/clients/traffic_client.py` and `app/models/traffic_contract.py`)
**contract_version**: `1.0.0`

### Request Body

```json
{
  "window_seconds": 60,
  "target_service": "demo-api",
  "trace_id": "trace-abc123def456"
}
```

| Field | Type | Required | Default | Constraint |
| :--- | :--- | :--- | :--- | :--- |
| `window_seconds` | integer | No | 60 | ≥ 1 |
| `target_service` | string | No | `"demo-api"` | — |
| `trace_id` | string | No | null | — |

### Response Body

```json
{
  "event_id": "c1f7b0f2-53b9-4f24-8b63-123456789abc",
  "trace_id": "trace-abc123def456",
  "timestamp": "2026-09-01T12:00:00Z",
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

| Field | Type | Constraint |
| :--- | :--- | :--- |
| `event_id` | string (UUIDv4) | — |
| `trace_id` | string | — |
| `timestamp` | string (ISO-8601) | — |
| `contract_version` | string (semver) | pattern `^\d+\.\d+\.\d+$` |
| `service_version` | string (semver) | — |
| `model_version` | string | — |
| `window_seconds` | integer | ≥ 1 |
| `total_rps` | float | ≥ 0.0 |
| `legitimate_rps_estimate` | float | ≥ 0.0 |
| `suspicious_rps_estimate` | float | ≥ 0.0 |
| `risk_score` | float | [0.0, 1.0] |
| `legitimacy_score` | float | [0.0, 1.0] |
| `confidence` | float | [0.0, 1.0] |
| `classification` | string (enum) | `legitimate` \| `suspicious` \| `malicious` \| `unknown` |
| `top_signals` | array of strings | — |

### Errors

| Status | Meaning |
| :--- | :--- |
| 200 | Success |
| 422 | Validation error (malformed request) |
| 500 | Internal server error |

---

## Contract 2: Demand Forecast

**Schema file**: `contracts/demand/demand_forecast.schema.json`
**Endpoint**: `POST /api/v1/demand/forecast` (Demand Intelligence service, port 8002)
**Producer**: Module 2 — Demand Intelligence (`services/demand-intelligence/`)
**Consumer**: Module 3 — Platform (via `app/clients/demand_client.py` and `app/models/demand_contract.py`)
**contract_version**: `1.0.0`

### Request Body

```json
{
  "forecast_horizon_seconds": 300,
  "trace_id": "trace-abc123def456"
}
```

| Field | Type | Required | Default | Constraint |
| :--- | :--- | :--- | :--- | :--- |
| `forecast_horizon_seconds` | integer | No | 300 | > 0 |
| `trace_id` | string | No | null | — |

### Response Body

```json
{
  "event_id": "e89c1d04-4fa2-47b8-bc81-abcdef012345",
  "trace_id": "trace-abc123def456",
  "generated_at": "2026-09-01T12:00:00Z",
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

| Field | Type | Constraint |
| :--- | :--- | :--- |
| `predicted_legitimate_rps` | float | ≥ 0.0 |
| `lower_bound_rps` | float | ≥ 0.0; ≤ predicted |
| `upper_bound_rps` | float | ≥ 0.0; ≥ predicted |
| `confidence` | float | [0.0, 1.0] |

### Errors

| Status | Meaning |
| :--- | :--- |
| 200 | Success |
| 422 | Validation error |

---

## Contract 3: Resource State

**Schema file**: `contracts/resources/resource_state.schema.json`
**Endpoint**: `GET /api/v1/resources/current?namespace=sentinelscale&workload=demo-api` (Platform service, port 8003)
**Producer**: Module 3 — Platform Resource Observer
**Consumer**: Decision Engine (internal), external dashboards/evaluation harnesses
**contract_version**: `1.0.0`

### Query Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `namespace` | string | `sentinelscale` | Kubernetes namespace |
| `workload` | string | `demo-api` | Deployment name |
| `X-Trace-ID` | header | null | Optional trace ID |

### Response Body

```json
{
  "event_id": "99b821a0-6211-419b-a010-0987654321fe",
  "trace_id": "trace-abc123def456",
  "timestamp": "2026-09-01T12:00:00Z",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "target_namespace": "sentinelscale",
  "target_workload": "demo-api",
  "cpu_utilization": 0.68,
  "memory_utilization": 0.52,
  "cpu_requested_cores": 4.0,
  "cpu_limit_cores": 8.0,
  "memory_requested_bytes": 4294967296,
  "memory_limit_bytes": 8589934592,
  "running_pods": 4,
  "desired_pods": 4,
  "pending_pods": 0,
  "request_rate": 2500.0,
  "p95_latency_ms": 42.5,
  "error_rate": 0.002,
  "current_capacity_rps": 1400.0,
  "estimated_required_capacity_rps": 1200.0,
  "estimated_resource_waste": 0.14
}
```

| Field | Type | Constraint | Provider source (Phase 2A) |
| :--- | :--- | :--- | :--- |
| `cpu_utilization` | float | ≥ 0.0 | Prometheus (0.0 from K8s-only provider) |
| `memory_utilization` | float | ≥ 0.0 | Prometheus (0.0 from K8s-only provider) |
| `cpu_requested_cores` | float | ≥ 0.0 | Kubernetes pod container specs |
| `cpu_limit_cores` | float | ≥ 0.0 | Kubernetes pod container specs |
| `memory_requested_bytes` | integer | ≥ 0 | Kubernetes pod container specs |
| `memory_limit_bytes` | integer | ≥ 0 | Kubernetes pod container specs |
| `running_pods` | integer | ≥ 0 | Kubernetes pod phases |
| `desired_pods` | integer | ≥ 0 | Kubernetes deployment spec.replicas |
| `pending_pods` | integer | ≥ 0 | Kubernetes pod phases |
| `request_rate` | float | ≥ 0.0 | Prometheus |
| `p95_latency_ms` | float | ≥ 0.0 | Prometheus |
| `error_rate` | float | [0.0, 1.0] | Prometheus |
| `current_capacity_rps` | float | ≥ 0.0 | Derived: running_pods × pod_capacity |
| `estimated_required_capacity_rps` | float | ≥ 0.0 | Derived |
| `estimated_resource_waste` | float | [0.0, 1.0] | Derived |

### Errors

| Status | Meaning |
| :--- | :--- |
| 200 | Success |
| 502 | Telemetry provider failure (upstream unreachable, auth failed, timeout) |

---

## Contract 4: Decision Context (Input to Decision Engine)

**Schema file**: `contracts/decisions/decision_context.schema.json`
**Endpoint**: `POST /api/v1/decision/evaluate` (Platform service, port 8003)
**Producer**: External caller (or internal aggregator)
**Consumer**: Module 3 — Decision Engine
**contract_version**: `1.0.0`

### Request Body

```json
{
  "context_id": "<uuid>",
  "trace_id": "trace-abc123",
  "timestamp": "2026-09-01T12:00:00Z",
  "contract_version": "1.0.0",
  "target_workload": "demo-api",
  "traffic_assessment": { ...TrafficAssessment... },
  "demand_forecast": { ...DemandForecast... },
  "resource_state": { ...ResourceState... },
  "policy_overrides": {
    "min_pods": 2,
    "max_pods": 20,
    "target_cpu_utilization": 0.70,
    "pod_rps_capacity": 350.0
  },
  "dry_run": true,
  "shadow_mode": true
}
```

| Field | Type | Required | Default |
| :--- | :--- | :--- | :--- |
| `context_id` | string | Yes | — |
| `trace_id` | string | Yes | — |
| `timestamp` | string (ISO-8601) | Yes | — |
| `contract_version` | string (semver) | Yes | — |
| `target_workload` | string | Yes | — |
| `traffic_assessment` | TrafficAssessment | Yes | — |
| `demand_forecast` | DemandForecast | Yes | — |
| `resource_state` | ResourceState | Yes | — |
| `policy_overrides` | PolicyOverrides | No | null |
| `dry_run` | boolean | No | true |
| `shadow_mode` | boolean | No | true |

**Important**: Even if `dry_run=False` is sent, the `DecisionEngine` hardcodes `dry_run=True` in its output. This is a safety invariant in the code.

---

## Contract 5: Scaling Decision (Output of Decision Engine)

**Schema file**: `contracts/decisions/scaling_decision.schema.json`
**Endpoint**: `POST /api/v1/decision/evaluate` (response)
**Producer**: Module 3 — Decision Engine
**Consumer**: Shadow evaluation harnesses, future infrastructure actuators
**contract_version**: `1.0.0`

### Response Body

```json
{
  "decision_id": "<uuid>",
  "event_id": "<uuid>",
  "trace_id": "...",
  "timestamp": "...",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "model_version": "policy-rules-v0",
  "action": "HOLD",
  "reason": "High security risk (0.84) detected...",
  "confidence": 0.91,
  "traffic_risk": 0.84,
  "predicted_legitimate_rps": 1200.0,
  "current_capacity_rps": 1400.0,
  "current_pods": 4,
  "recommended_pods": 4,
  "baseline_hpa_recommended_pods": 8,
  "pod_delta_vs_baseline": -4,
  "policy": "default-safe-guardrail-v1",
  "dry_run": true,
  "shadow_mode": true
}
```

| Field | Type | Constraint |
| :--- | :--- | :--- |
| `action` | string (enum) | `SCALE` \| `RATE_LIMIT` \| `MITIGATE` \| `HOLD` |
| `confidence` | float | [0.0, 1.0] — avg of traffic and demand confidence |
| `traffic_risk` | float | [0.0, 1.0] |
| `pod_delta_vs_baseline` | integer | negative = pods saved vs HPA |
| `dry_run` | boolean | Always `true` in current implementation |

---

## Internal Python Interfaces

### `ResourceTelemetryProvider` (ABC)

**File**: `services/platform/app/services/telemetry/base.py`

```python
class ResourceTelemetryProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def fetch_resource_state(
        self,
        namespace: str,
        workload: str,
        trace_id: Optional[str] = None
    ) -> ResourceState: ...
```

**Raises**: `TelemetryProviderError` on any failure — never returns a fake/zero result silently.

### `get_telemetry_provider()` (Factory)

**File**: `services/platform/app/services/telemetry/factory.py`

```python
def get_telemetry_provider(provider_type: Optional[str] = None) -> ResourceTelemetryProvider:
    # Reads TELEMETRY_PROVIDER env var if provider_type is None
    # Returns MockTelemetryProvider | PrometheusTelemetryProvider | KubernetesTelemetryProvider
    # Raises TelemetryProviderError for unknown provider_type
```

### `DecisionEngine.evaluate_decision()`

**File**: `services/platform/app/services/decision_engine.py`

```python
async def evaluate_decision(self, context: DecisionContext) -> ScalingDecision:
    # Always returns dry_run=True regardless of context.dry_run
```

### HTTP Client Interfaces (Module 3 → Module 1/2)

**Files**: `services/platform/app/clients/traffic_client.py`, `demand_client.py`

```python
class TrafficIntelligenceClient:
    async def fetch_assessment(window_seconds: int, trace_id: Optional[str]) -> TrafficAssessment:
        # POST http://traffic-intelligence:8001/api/v1/traffic/assess
        # Raises httpx.HTTPStatusError on non-200

class DemandIntelligenceClient:
    async def fetch_forecast(forecast_horizon_seconds: int, trace_id: Optional[str]) -> DemandForecast:
        # POST http://demand-intelligence:8002/api/v1/demand/forecast
        # Raises httpx.HTTPStatusError on non-200
```

---

## System Health Endpoints

Available on all 4 services:

| Endpoint | Method | Response |
| :--- | :--- | :--- |
| `/health` | GET | `{"status": "ok", "service": "<name>"}` |
| `/ready` | GET | `{"status": "ready", "service": "<name>"}` |
| `/version` | GET | Service metadata including contract_version, model_version, dry_run, shadow_mode |
