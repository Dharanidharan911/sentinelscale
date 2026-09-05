# Data Flow — SentinelScale

> Last updated: 2026-09-05
> Source of truth: actual implementation and Stage F1–F6 validation in this repository

This document traces how data moves through the SentinelScale system, from ingress API traffic to comparative scaling evaluations.

---

## 1. Top-Level Data Flow

```
[ API Traffic ] ──► [ Demo API :8000 ]
                           │
                 [ Telemetry Collector ]
                           │ (TrafficTelemetryInput)
                           ▼
          [ Module 1: Traffic Intelligence :8001 ]
                           │ (TrafficAssessment: risk_score, legitimate_rps_estimate)
                           ▼
         [ F2 Demand Observation Accumulator (SQLite) ]
                           │ (Security Gating: Risk <= 0.80, Class != malicious)
                           ▼ (DemandObservation[])
          [ Module 2: Demand Intelligence :8002 ]
                           │ (DemandForecast: predicted_legitimate_rps, confidence)
                           ▼
         [ Module 3: Context Aggregator & Platform :8003 ]
            ├── ResourceObserver ──► ResourceState
            ├── TrafficAssessment
            └── DemandForecast
                           │ (DecisionContext)
                           ▼
                 [ Decision Engine ]
                           │
                 [ Policy Guardrails ]
                           │
                 [ ScalingDecision ] ──► [ Evaluator ] ──► [ EvaluationResult ]
                 (dry_run=true, shadow_mode=true)
```

---

## 2. Stage-by-Stage Closed-Loop Data Flow

### Stage 1: Ingress Traffic Generation & Empirical Observation

**Input**: Real or generated HTTP requests targeting `demo-api` business endpoints (`/api/v1/products`, `/users`).

**Processing** (`services/platform/app/harness/`):
- `AsyncTrafficGenerator` dispatches requests with realistic client distributions, HTTP methods, headers, and User-Agents.
- `TelemetryCollector` aggregates individual request events across the observation window:
  - `total_requests` and `total_rps`
  - `status_codes` (2xx, 3xx, 4xx, 5xx counts and error rate)
  - `top_ip_ratio` (IP concentration) and `unique_ip_count`
  - `non_standard_ua_ratio` (bot and anomaly ratio)
  - `single_endpoint_ratio`

**Output**: `TrafficTelemetryInput` payload.

---

### Stage 2: Traffic Telemetry → Module 1 → TrafficAssessment

**Input**: HTTP `POST http://traffic-intelligence:8001/api/v1/traffic/assess` with `AssessmentRequest` containing `TrafficTelemetryInput`.

**Processing** (`services/traffic-intelligence/app/`):
- Evaluates burstiness, IP concentration, User-Agent anomaly rates, and error rates using `traffic-rules-v1`.
- Categorizes traffic into `legitimate`, `suspicious`, or `malicious`.
- Derives `legitimate_rps_estimate` by filtering out suspicious/malicious traffic proportions.
- Assigns `risk_score` $[0.0, 1.0]$, `legitimacy_score` $[0.0, 1.0]$, and `confidence` $[0.0, 1.0]$.

**Output**: `TrafficAssessment` (Contract: `contracts/traffic/traffic_assessment.schema.json`).

---

### Stage 3: TrafficAssessment → F2 Accumulator (SQLite) → Legitimate Demand History

**Input**: `TrafficAssessment` emitted by Module 1.

**Processing** (`services/platform/app/services/history/demand_accumulator.py`):
1. **Timestamp & Numeric Validation**: Verifies ISO-8601 timestamps and finite non-negative RPS values.
2. **Security Gating**:
   - Rejects observations if `classification == 'malicious'` or `risk_score > 0.80`.
   - Rejects observations if `legitimacy_score < 0.20` or `confidence < 0.30`.
   - **Critical Invariant**: Raw attack traffic is completely blocked at this gate.
3. **Persistence & Deduplication**: Inserts accepted observations into SQLite `demand_observations` table keyed by `event_id`.

**Output**: Bounded chronological sequence of `DemandObservation(timestamp, rps)` records.

---

### Stage 4: Historical Demand Observations → Module 2 → DemandForecast

**Input**: HTTP `POST http://demand-intelligence:8002/api/v1/demand/forecast` with `ForecastRequest` containing `DemandObservation[]`.

**Processing** (`services/demand-intelligence/app/engine/forecaster.py`):
- Preprocesses and sorts historical legitimate observations.
- Computes **recency-weighted moving average** (exponential decay based on observation age).
- Computes **linear trend slope** when time span ($\ge 120\text{s}$) and sample count ($\ge 5$) warrant trend projection.
- Derives prediction bounds: `lower_bound_rps` and `upper_bound_rps`.
- Calculates statistical confidence based on sample count, coefficient of variation, sampling regularity, and forecast horizon.

**Output**: `DemandForecast` (Contract: `contracts/demand/demand_forecast.schema.json`).

---

### Stage 5: Resource Telemetry → Module 3 Resource Observer → ResourceState

**Input**: Query to `ResourceObserverService.get_current_resource_state()`.

**Processing** (via configured `ResourceTelemetryProvider`):
- **Mock Provider (default)**: Returns deterministic cluster resource state for local development.
- **Prometheus Provider**: Queries CPU/memory utilization ratios, request rate, P95 latency, and error rate.
- **Kubernetes Provider**: Queries pod phases, container specs, and Deployment replica counts.
- **Hybrid Provider**: Concurrently merges Kubernetes infrastructure counts with Prometheus performance metrics.

**Output**: `ResourceState` (Contract: `contracts/resources/resource_state.schema.json`).

---

### Stage 6: Decision Context Aggregation → Decision Engine → ScalingDecision

**Input**: `DecisionContext` containing `TrafficAssessment`, `DemandForecast`, and `ResourceState`.

**Processing** (`services/platform/app/services/decision_engine.py`):
1. **Baseline Reactive HPA**: Computes reactive replica count based blindly on CPU utilization:
   $$\text{hpa\_pods} = \text{clamp}\left(\left\lceil \text{current\_pods} \times \frac{\text{cpu\_utilization}}{\text{target\_cpu\_utilization}} \right\rceil, \text{min\_pods}, \text{max\_pods}\right)$$
2. **SentinelScale Capacity Calculation**: Computes required replicas based strictly on legitimate demand:
   $$\text{raw\_sentinel\_pods} = \left\lceil \frac{\text{predicted\_legitimate\_rps}}{\text{pod\_rps\_capacity}} \right\rceil$$
3. **Policy Guardrails Enforcement**: Applies min/max bounds and 2x step-surge rate-of-change limits.
4. **Action Determination**:
   - If `risk_score >= 0.70` and demand fits capacity $\rightarrow$ `action = HOLD` (suppresses attack scale-out).
   - If demand exceeds capacity $\rightarrow$ `action = SCALE` (proactive legitimate scale-up).
   - If demand is significantly below capacity $\rightarrow$ `action = SCALE` (safe scale-down).
   - Otherwise $\rightarrow$ `action = HOLD` (well-balanced).
5. **Safety Injection**: Sets `dry_run = True` and `shadow_mode = True`.

**Output**: `ScalingDecision` (Contract: `contracts/decisions/scaling_decision.schema.json`).

---

### Stage 7: ScalingDecision → Comparative Evaluator → EvaluationResult

**Input**: `DecisionContext` or `ScalingDecision`.

**Processing** (`services/platform/app/services/evaluation/evaluator.py`):
- Computes `replica_delta = sentinelscale_pods - hpa_pods`.
- Computes `estimated_pod_hours_saved_per_hour = max(0, hpa_pods - sentinelscale_pods)`.
- Flags `unnecessary_scale_up_signal = True` when HPA scales on attack traffic while legitimate demand is satisfied.
- Assigns evaluation category (`ALIGNED`, `SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE`, `SENTINELSCALE_PROACTIVELY_SCALES`, `SCALE_DOWN_DIFFERENCE`, or `UNCERTAIN`).

**Output**: `EvaluationResult` model.

---

## 3. Distributed Trace Propagation

Every transaction carries a unique `trace_id` propagated across all service boundaries:

```
Scenario Definition (trace_id)
        ↓
HTTP Header: X-Trace-ID ──► Demo API (:8000)
        ↓
HTTP Header: X-Trace-ID ──► Module 1 (:8001) ──► TrafficAssessment.trace_id
        ↓
SQLite Column: trace_id ──► demand_observations table
        ↓
HTTP Header: X-Trace-ID ──► Module 2 (:8002) ──► DemandForecast.trace_id
        ↓
HTTP Header: X-Trace-ID ──► Module 3 (:8003) ──► DecisionContext.trace_id
        ↓
ScalingDecision.trace_id ──► EvaluationResult.trace_id
```

---

## 4. Error Handling & Failure Isolation

1. **Explicit Error Representation**: Telemetry provider failures raise `TelemetryProviderError` and surface as `HTTP 502 Bad Gateway`, never silently falling back to zero.
2. **Observation Isolation**: Module 2 forecasting failures surface as typed HTTP exceptions (`HTTP 422 Unprocessable Entity` for insufficient data, `HTTP 503` for unavailable provider), preventing corrupted forecasts from reaching the Decision Engine.
3. **Database Fault Tolerance**: SQLite writes utilize transactions with thread locks and WAL mode to prevent concurrency conflicts.
