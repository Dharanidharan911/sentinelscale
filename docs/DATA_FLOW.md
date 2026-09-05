# Data Flow — SentinelScale

> Last updated: 2026-09-01

This document traces how data moves through the system from ingress traffic to scaling decisions.

---

## 1. Top-Level Data Flow

```
[API Clients] → [API Gateway] → [demo-api :8000]
                                     │
                            [Prometheus :9090] ◄── scrapes /metrics
                                     │
         ┌───────────────────────────┼───────────────────┐
         ▼                           ▼                   ▼
  [Traffic Intelligence]   [Demand Intelligence]   [Platform: Resource Observer]
     POST /assess              POST /forecast          fetch_resource_state()
         │                           │                       │
  TrafficAssessment           DemandForecast            ResourceState
         └───────────────────────────┼───────────────────────┘
                                     ▼
                              [DecisionContext]
                             POST /decision/evaluate
                                     │
                              [Decision Engine]
                                     │
                           [Policy Guardrails]
                                     │
                              [ScalingDecision]
                          (dry_run=true, shadow_mode=true)
                                     │
                              [Logs / Shadow Eval]
```

---

## 2. Stage-by-Stage Data Flow

### Stage 1: Incoming Traffic → Demo API → Prometheus

**Input**: Real or simulated HTTP requests to `demo-api` endpoints (products, users, cart).

**Processing** (`demo-api/app/metrics.py`):
- `PrometheusMetricsMiddleware` intercepts every request
- Records: `http_requests_total` (count by method, path, status), `http_request_duration_seconds` (histogram)
- Exposed at `GET /metrics` in Prometheus text format

**Output**: Prometheus metrics exposed for scraping.

**Data format**: Prometheus text exposition format (counter, histogram, gauge)

**Important assumption**: Prometheus scrapes `/metrics` every 5 seconds (configured in `telemetry/prometheus/prometheus.yml`).

---

### Stage 2: Traffic Telemetry → Module 1 → TrafficAssessment

**Input**: `POST /api/v1/traffic/assess`
```json
{
  "window_seconds": 60,
  "target_service": "demo-api",
  "trace_id": "trace-abc123"
}
```

**Processing** (current: mock):
- `TrafficAssessmentService.assess_traffic()` → `MockTrafficDataGenerator.generate_assessment()`
- Returns deterministic fixed-value payload (risk_score=0.84, suspicious)

**Output**: `TrafficAssessment` JSON
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

**Data types**: risk_score/legitimacy_score/confidence ∈ [0.0, 1.0], classification ∈ enum{legitimate, suspicious, malicious, unknown}

**Schema**: `contracts/traffic/traffic_assessment.schema.json`

---

### Stage 3: Historical Telemetry → Module 2 → DemandForecast

**Input**: `POST /api/v1/demand/forecast`
```json
{
  "forecast_horizon_seconds": 300,
  "trace_id": "trace-abc123"
}
```

**Processing** (current: mock):
- `DemandForecastingService.forecast_demand()` → `MockDemandDataGenerator.generate_forecast()`
- Returns deterministic fixed-value payload (predicted_rps=1200, confidence=0.91)

**Important**: Module 2 operates **asynchronously and independently** from Module 1 — it does NOT call Module 1 at runtime. This is a hard architectural invariant.

**Output**: `DemandForecast` JSON
```json
{
  "event_id": "<uuid>",
  "trace_id": "...",
  "generated_at": "...",
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

**Data types**: predicted_legitimate_rps/lower_bound/upper_bound ≥ 0.0; invariant: lower_bound ≤ predicted ≤ upper_bound; confidence ∈ [0.0, 1.0]

**Schema**: `contracts/demand/demand_forecast.schema.json`

---

### Stage 4: Kubernetes/Prometheus → Module 3 Resource Observer → ResourceState

**Input**: `GET /api/v1/resources/current?namespace=sentinelscale&workload=demo-api`
(No request body — query parameters only)

**Processing** (provider-dependent, selected by `TELEMETRY_PROVIDER` env var):

#### Mock Provider (default)
- Calls `MockResourceDataGenerator.generate_current_state()`
- Returns fixed deterministic values

#### Prometheus Provider (`TELEMETRY_PROVIDER=prometheus`)
- Queries Prometheus HTTP API: `GET {PROMETHEUS_URL}/api/v1/query`
- PromQL for CPU utilization: normalized ratio (actual usage / limit), NOT raw cores
- PromQL for memory utilization: normalized ratio, NOT raw bytes
- PromQL for request_rate: rate of http_requests_total over window
- PromQL for p95_latency_ms: histogram_quantile(0.95, ...)
- PromQL for error_rate: rate of 5xx errors / total rate
- On missing denominator (unavailable capacity metric): raises `TelemetryProviderError` explicitly
- No silent zero fallbacks for genuine metric failures

#### Kubernetes Provider (`TELEMETRY_PROVIDER=kubernetes`)
- `GET /apis/apps/v1/namespaces/{ns}/deployments/{workload}` → desired_pods, matchLabels
- `GET /api/v1/namespaces/{ns}/pods?labelSelector={labels}` → pod list with phases + container specs
- Pod phases: Running → running_pods, Pending → pending_pods, Failed/Succeeded/Unknown → excluded
- Aggregates container `resources.requests` and `resources.limits` across all Running pods
- `quantity_parser.py` converts Kubernetes quantities (100m, 256Mi, 2G) to float cores / int bytes
- cpu_utilization = 0.0 (unavailable from Kubernetes API alone — needs Prometheus)
- memory_utilization = 0.0 (same limitation)

**Output**: `ResourceState` JSON
```json
{
  "event_id": "<uuid>",
  "trace_id": "...",
  "timestamp": "...",
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

**Derived fields**:
- `current_capacity_rps = running_pods × DEFAULT_POD_RPS_CAPACITY` (= 350.0 per pod, configurable)
- `estimated_resource_waste = max(0, (current_capacity_rps - demand_rps) / current_capacity_rps)`

**Schema**: `contracts/resources/resource_state.schema.json`

---

### Stage 5: All Signals → DecisionContext → Decision Engine → ScalingDecision

**Input**: `POST /api/v1/decision/evaluate` with `DecisionContext` body:
```json
{
  "context_id": "<uuid>",
  "trace_id": "...",
  "timestamp": "...",
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

**Processing** (`DecisionEngine.evaluate_decision()`):
1. Extract: `current_pods = resource_state.running_pods`, `current_capacity = current_capacity_rps`, `predicted_legitimate = demand.predicted_legitimate_rps`
2. Calculate: `baseline_hpa_pods = BaselineHPACalculator.calculate_baseline_replicas(resource_state)`
3. Calculate: `raw_sentinel_pods = ceil(predicted_legitimate / pod_capacity)`
4. Apply: `recommended_pods, guardrail_reason = PolicyGuardrail.apply_guardrails(raw_sentinel_pods, context)`
5. Determine action via decision tree (see Architecture doc)
6. Compute: `pod_delta_vs_baseline = recommended_pods - baseline_hpa_pods`
7. Compute: `composite_confidence = (traffic.confidence + demand.confidence) / 2.0`

**Output**: `ScalingDecision` JSON
```json
{
  "decision_id": "<uuid>",
  "event_id": "...",
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

**Schema**: `contracts/decisions/scaling_decision.schema.json`

---

## 3. Distributed Tracing

Every request carries a `trace_id` (format: `trace-{16-char hex}`) propagated through all contracts:
- Generated at entry point if not present
- Passed as `X-Trace-ID` HTTP header between services
- Embedded in every contract payload's `trace_id` field
- Used for correlating events across Module 1, 2, and 3 logs

---

## 4. Error Handling Data Flow

When a telemetry provider fails:

```
KubernetesTelemetryProvider.fetch_resource_state()
    → httpx.TimeoutException / httpx.RequestError / HTTP 4xx/5xx
    → raise TelemetryProviderError(provider_name, message, original_error)
         ↓
ResourceObserverService.get_current_resource_state()
    → propagates TelemetryProviderError upward
         ↓
endpoints.py: get_current_resources()
    → except TelemetryProviderError → HTTPException(status_code=502, detail=...)
         ↓
Client receives HTTP 502 Bad Gateway with structured error detail
```

**Key principle**: Errors are always explicit. There are no silent fallbacks to zero values for genuine infrastructure failures.

---

## 5. Module 2B Data Flow (Planned — NOT IMPLEMENTED)

Phase 2B is intended to combine Prometheus application metrics with Kubernetes infrastructure state into a single hybrid `ResourceState`. This would mean:

- CPU utilization and memory utilization: from **Prometheus** (normalized ratios)
- Running pods, desired pods, pending pods: from **Kubernetes API** (real pod phases)
- Container resource limits/requests: from **Kubernetes API** (actual running pod specs)
- Request rate, P95 latency, error rate: from **Prometheus**
- Derived capacity metrics: computed from Kubernetes pod counts + Prometheus throughput

See [`docs/MODULE_2B.md`](MODULE_2B.md) for the full specification.
