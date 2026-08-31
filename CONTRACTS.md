# SentinelScale API Contracts Specification

This document establishes the public interfaces and communication contracts between SentinelScale modules.
All contracts are formal JSON Schemas stored under `contracts/` and strictly enforced at runtime via Pydantic v2 models.

> [!IMPORTANT]
> **Contract Immutability Rule**:
> Contracts are treated as public interfaces. No individual developer, subagent, or team member may silently modify contracts.
> Any breaking schema change requires explicit team review, version bumping, and backward compatibility evaluation.

---

## Standard Metadata Header

Every contract payload includes standard distributed observability metadata:

| Field | Type | Description |
| :--- | :--- | :--- |
| `event_id` | `UUIDv4` | Unique identifier for the discrete event or evaluation snapshot. |
| `trace_id` | `String` | Distributed tracing ID linking telemetry across upstream and downstream services. |
| `contract_version` | `SemVer` | Semantic version of the contract specification (e.g. `1.0.0`). |
| `service_version` | `SemVer` | Semantic version of the microservice producing the payload (e.g. `0.1.0`). |
| `model_version` | `String` | Version identifier of the heuristic, rule engine, or ML model (e.g. `traffic-v0`, `demand-v0`). |

---

## 1. Traffic Assessment Contract

- **Schema File**: [`contracts/traffic/traffic_assessment.schema.json`](file:///c:/SentinelScale/contracts/traffic/traffic_assessment.schema.json)
- **Producer**: Module 1 — Traffic Intelligence (`services/traffic-intelligence`)
- **Consumer**: Module 3 — Platform & Decision Engine (`services/platform`)
- **Endpoint**: `POST /api/v1/traffic/assess`

### Specification

```json
{
  "event_id": "c1f7b0f2-53b9-4f24-8b63-123456789abc",
  "trace_id": "trace-4a9b2c8d1e0f3456",
  "timestamp": "2026-08-31T18:30:00Z",
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
  "top_signals": [
    "high_burst_rate",
    "client_ip_concentration",
    "non_standard_user_agent"
  ]
}
```

### Constraints & Types
- `risk_score`, `legitimacy_score`, `confidence`: Floats bounded in $[0.0, 1.0]$.
- `classification`: Enum: `["legitimate", "suspicious", "malicious", "unknown"]`.
- `total_rps`, `legitimate_rps_estimate`, `suspicious_rps_estimate`: Non-negative floats.

---

## 2. Demand Forecast Contract

- **Schema File**: [`contracts/demand/demand_forecast.schema.json`](file:///c:/SentinelScale/contracts/demand/demand_forecast.schema.json)
- **Producer**: Module 2 — Demand Intelligence (`services/demand-intelligence`)
- **Consumer**: Module 3 — Platform & Decision Engine (`services/platform`)
- **Endpoint**: `POST /api/v1/demand/forecast`

### Specification

```json
{
  "event_id": "e89c1d04-4fa2-47b8-bc81-abcdef012345",
  "trace_id": "trace-4a9b2c8d1e0f3456",
  "generated_at": "2026-08-31T18:30:00Z",
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

### Constraints & Types
- `forecast_horizon_seconds`: Positive integer (seconds).
- `predicted_legitimate_rps`, `lower_bound_rps`, `upper_bound_rps`: Non-negative floats with invariant `lower_bound <= predicted <= upper_bound`.
- `confidence`: Float bounded in $[0.0, 1.0]$.

---

## 3. Resource State Contract

- **Schema File**: [`contracts/resources/resource_state.schema.json`](file:///c:/SentinelScale/contracts/resources/resource_state.schema.json)
- **Producer**: Module 3 — Resource Observer (`services/platform`)
- **Consumer**: Decision Engine, Dashboard, Evaluation harnesses
- **Endpoint**: `GET /api/v1/resources/current`

### Specification

```json
{
  "event_id": "99b821a0-6211-419b-a010-0987654321fe",
  "trace_id": "trace-4a9b2c8d1e0f3456",
  "timestamp": "2026-08-31T18:30:00Z",
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

---

## 4. Decision Context Contract

- **Schema File**: [`contracts/decisions/decision_context.schema.json`](file:///c:/SentinelScale/contracts/decisions/decision_context.schema.json)
- **Producer**: Platform / Context Aggregator
- **Consumer**: Decision Engine & Policy Guardrails
- **Endpoint**: Ingested by `POST /api/v1/decision/evaluate`

### Specification
Aggregates `traffic_assessment`, `demand_forecast`, `resource_state`, execution flags (`dry_run`, `shadow_mode`), and optional `policy_overrides`.

---

## 5. Scaling Decision Contract

- **Schema File**: [`contracts/decisions/scaling_decision.schema.json`](file:///c:/SentinelScale/contracts/decisions/scaling_decision.schema.json)
- **Producer**: Module 3 — Decision Engine (`services/platform`)
- **Consumer**: Infrastructure Actuators (future), Alerting, Shadow Comparison Dashboard
- **Endpoint**: `POST /api/v1/decision/evaluate`

### Specification

```json
{
  "decision_id": "f512702c-4933-4df4-a827-0123456789aa",
  "event_id": "c1f7b0f2-53b9-4f24-8b63-123456789abc",
  "trace_id": "trace-4a9b2c8d1e0f3456",
  "timestamp": "2026-08-31T18:30:00Z",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "model_version": "policy-rules-v0",
  "action": "HOLD",
  "reason": "High security risk (0.84) detected with suspicious traffic. Predicted legitimate demand (1200.0 RPS) is within current capacity (1400.0 RPS). Prevented reactive overprovisioning of 4 pods.",
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

### Supported Actions:
- `SCALE`: Adjust container replica count according to legitimate demand.
- `RATE_LIMIT`: Trigger adaptive gateway rate-limiting for high-risk clients.
- `MITIGATE`: Trigger challenge injection or IP blackholing at ingress.
- `HOLD`: Retain current replica capacity; suppress naive reactive scale-out.

---

## Contract Versioning & Compatibility Rules

1. **Semantic Versioning (`MAJOR.MINOR.PATCH`)**:
   - `PATCH`: Documentation or description clarifications without schema constraints changes.
   - `MINOR`: Adding non-required optional fields.
   - `MAJOR`: Renaming fields, removing fields, adding mandatory fields, changing types, or altering enum domains.
2. **Automated CI Validation**:
   - Every commit triggers `test_contract_conformance.py` in all services, verifying that Pydantic models validate successfully against JSON Schemas.
