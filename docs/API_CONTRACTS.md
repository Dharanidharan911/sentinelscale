# API Contracts — SentinelScale

> Last updated: 2026-09-05
> Canonical JSON Schema files: `contracts/`

> [!IMPORTANT]
> Contracts are frozen public interfaces (`contract_version: "1.0.0"`). Any breaking change requires a major version bump and team review.

---

## Contract 1: Traffic Assessment

- **Schema File**: `contracts/traffic/traffic_assessment.schema.json`
- **Endpoint**: `POST /api/v1/traffic/assess` (Traffic Intelligence service, port 8001)
- **Producer**: Module 1 — Traffic Intelligence (`services/traffic-intelligence/`)
- **Consumer**: Module 3 — Platform (via `app/clients/traffic_client.py`)
- **contract_version**: `1.0.0`

### Request Body (`AssessmentRequest`)

```json
{
  "window_seconds": 60,
  "target_service": "demo-api",
  "trace_id": "f6-steady-001",
  "telemetry": {
    "total_requests": 50,
    "total_rps": 50.0,
    "baseline_rps": 50.0,
    "status_codes": {
      "status_2xx": 50,
      "status_3xx": 0,
      "status_4xx": 0,
      "status_5xx": 0
    },
    "top_ip_ratio": 0.08,
    "unique_ip_count": 25,
    "non_standard_ua_ratio": 0.0,
    "single_endpoint_ratio": 0.5
  }
}
```

### Response Body (`TrafficAssessment`)

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

## Contract 2: Demand Forecast

- **Schema File**: `contracts/demand/demand_forecast.schema.json`
- **Endpoint**: `POST /api/v1/demand/forecast` (Demand Intelligence service, port 8002)
- **Producer**: Module 2 — Demand Intelligence (`services/demand-intelligence/`)
- **Consumer**: Module 3 — Platform (via `app/clients/demand_client.py`)
- **contract_version**: `1.0.0`

### Request Body (`ForecastRequest`)

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

### Response Body (`DemandForecast`)

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

## Contract 3: Resource State

- **Schema File**: `contracts/resources/resource_state.schema.json`
- **Endpoint**: `GET /api/v1/resources/current?namespace=sentinelscale&workload=demo-api` (Platform service, port 8003)
- **Producer**: Module 3 — Platform Resource Observer
- **Consumer**: Decision Engine, Context Aggregator, Dashboard
- **contract_version**: `1.0.0`

### Response Body (`ResourceState`)

```json
{
  "event_id": "99b821a0-6211-419b-a010-0987654321fe",
  "trace_id": "f6-steady-001",
  "timestamp": "2026-09-05T12:00:00Z",
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
  "request_rate": 50.0,
  "p95_latency_ms": 12.5,
  "error_rate": 0.0,
  "current_capacity_rps": 1400.0,
  "estimated_required_capacity_rps": 54.9,
  "estimated_resource_waste": 0.96
}
```

---

## Contract 4: Decision Context

- **Schema File**: `contracts/decisions/decision_context.schema.json`
- **Endpoint**: `POST /api/v1/decision/evaluate` / `POST /api/v1/decision/aggregate` (port 8003)
- **Producer**: Context Aggregator / Orchestration Harness
- **Consumer**: Module 3 — Decision Engine & Evaluator
- **contract_version**: `1.0.0`

### Request Body (`DecisionContext`)

```json
{
  "context_id": "ctx-9a7c3b2f1e0d",
  "trace_id": "f6-steady-001",
  "timestamp": "2026-09-05T12:00:00Z",
  "contract_version": "1.0.0",
  "target_workload": "demo-api",
  "traffic_assessment": { ...TrafficAssessment... },
  "demand_forecast": { ...DemandForecast... },
  "resource_state": { ...ResourceState... },
  "policy_overrides": null,
  "dry_run": true,
  "shadow_mode": true
}
```

---

## Contract 5: Scaling Decision

- **Schema File**: `contracts/decisions/scaling_decision.schema.json`
- **Endpoint**: `POST /api/v1/decision/evaluate` / `POST /api/v1/decision/orchestrate` (response)
- **Producer**: Module 3 — Decision Engine
- **Consumer**: Platform, Shadow Evaluation, Audit Store
- **contract_version**: `1.0.0`

### Response Body (`ScalingDecision`)

```json
{
  "decision_id": "d1c2b3a4-5678-90ab-cdef-1234567890ab",
  "event_id": "c1f7b0f2-53b9-4f24-8b63-123456789abc",
  "trace_id": "f6-steady-001",
  "timestamp": "2026-09-05T12:00:00Z",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "model_version": "policy-rules-v0",
  "action": "SCALE",
  "reason": "Legitimate demand significantly below current capacity. Scale-down recommended to 2 pods.",
  "confidence": 0.40,
  "traffic_risk": 0.05,
  "predicted_legitimate_rps": 54.9,
  "current_capacity_rps": 1400.0,
  "current_pods": 4,
  "recommended_pods": 2,
  "baseline_hpa_recommended_pods": 4,
  "pod_delta_vs_baseline": -2,
  "policy": "default-safe-guardrail-v1",
  "dry_run": true,
  "shadow_mode": true
}
```

---

## Formal Evaluation Endpoints

- **`POST /api/v1/evaluation/evaluate`**: Produces an `EvaluationResult` comparing reactive HPA vs. SentinelScale from a `DecisionContext`.
- **`GET /api/v1/evaluation/hpa-vs-sentinelscale`**: Retrieves formal comparative evaluation for a historical observation ID or the latest recorded observation.

### Response Body (`EvaluationResult`)

```json
{
  "evaluation_id": "eval-8899aabb-ccdd",
  "trace_id": "f6-steady-001",
  "timestamp": "2026-09-05T12:00:00Z",
  "category": "UNCERTAIN",
  "recommendation_difference": "SENTINELSCALE_FEWER_PODS",
  "explanation": "Low composite confidence (0.40 < 0.50). Comparative evaluation is marked uncertain due to degraded telemetry or forecast inputs.",
  "hpa_recommended_pods": 4,
  "sentinelscale_recommended_pods": 2,
  "current_pods": 4,
  "traffic_risk": 0.05,
  "predicted_legitimate_rps": 54.9,
  "current_capacity_rps": 1400.0,
  "confidence": 0.40,
  "metrics": {
    "replica_delta": -2,
    "absolute_replica_delta": 2,
    "estimated_pod_hours_saved_per_hour": 2.0,
    "estimated_cpu_cores_saved": null,
    "unnecessary_scale_up_signal": false,
    "capacity_satisfied": true,
    "suppression_reason": null
  },
  "dry_run": true,
  "shadow_mode": true
}
```
