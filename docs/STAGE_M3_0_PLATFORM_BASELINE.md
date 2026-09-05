# Stage M3-0 — Member 3 Platform Baseline Report

> **Baseline verification for Member 3 (Platform & Decision Engine) prior to M3-1 Prometheus Live Observability.**

---

## 1. Executive Baseline Summary

Stage M3-0 audits, verifies, and solidifies the **Platform & Decision Engine (Module 3)** baseline on branch `member3/platform` at commit `a0c5621`.

All core platform subsystems, deterministic decision logic, policy guardrails, comparative HPA evaluation, historical demand observation storage, telemetry provider abstractions, and frozen contracts were audited and confirmed functional without requiring production code rewrites.

---

## 2. Platform Subsystem Verification Matrix

| Subsystem | Primary Implementation | Verified Baseline Behavior | Status |
| :--- | :--- | :--- | :---: |
| **System Endpoints** | [`app/main.py`](file:///c:/SentinelScale/services/platform/app/main.py) | `/health` (HTTP 200), `/ready` (HTTP 200), `/version` (metadata + safety flags), `/metrics` (Prometheus text exposition format) | 🟢 VERIFIED |
| **Telemetry Provider Factory** | [`app/services/telemetry/factory.py`](file:///c:/SentinelScale/services/platform/app/services/telemetry/factory.py) | Supports `mock`, `prometheus`, `kubernetes`, and `hybrid` dynamically via `TELEMETRY_PROVIDER` | 🟢 VERIFIED |
| **Context Aggregator** | [`app/services/context_aggregator.py`](file:///c:/SentinelScale/services/platform/app/services/context_aggregator.py) | Concurrently aggregates M1 `TrafficAssessment`, M2 `DemandForecast`, and `ResourceState` via `asyncio.gather` | 🟢 VERIFIED |
| **Decision Engine** | [`app/services/decision_engine.py`](file:///c:/SentinelScale/services/platform/app/services/decision_engine.py) | Deterministic capacity evaluation comparing legitimate predicted demand against resource capacity | 🟢 VERIFIED |
| **Baseline HPA Calculator** | [`app/services/baseline_hpa.py`](file:///c:/SentinelScale/services/platform/app/services/baseline_hpa.py) | Standard reactive Kubernetes HPA formula: `ceil(current_pods * (current_cpu / target_cpu))` | 🟢 VERIFIED |
| **Policy Guardrails** | [`app/services/policy_guardrail.py`](file:///c:/SentinelScale/services/platform/app/services/policy_guardrail.py) | Clamps scaling recommendations (`min_pods=1`, `max_pods=10`, step-up `<= 2`, step-down `<= 1`, cooldowns) | 🟢 VERIFIED |
| **HPA Evaluation Service** | [`app/services/evaluation/evaluator.py`](file:///c:/SentinelScale/services/platform/app/services/evaluation/evaluator.py) | Formal comparative evaluation producing `replica_delta`, `pod_hours_saved_per_hour`, and classification category | 🟢 VERIFIED |
| **Historical Demand Accumulator** | [`app/services/history/demand_accumulator.py`](file:///c:/SentinelScale/services/platform/app/services/history/demand_accumulator.py) | Rejects attack observations (`risk_score > 0.80`, `classification == 'malicious'`), persists clean history to SQLite | 🟢 VERIFIED |
| **Decision History Store** | [`app/services/history/sqlite_store.py`](file:///c:/SentinelScale/services/platform/app/services/history/sqlite_store.py) | SQLite WAL mode storage for observations and scaling decisions (`data/sentinelscale_history.db`) | 🟢 VERIFIED |
| **Predictive Intelligence** | [`app/services/intelligence/predictive.py`](file:///c:/SentinelScale/services/platform/app/services/intelligence/predictive.py) | Deterministic Ordinary Least Squares (OLS) linear trend regression over historical observations | 🟢 VERIFIED |
| **Continuous Scheduler** | [`app/services/observation_scheduler.py`](file:///c:/SentinelScale/services/platform/app/services/observation_scheduler.py) | Periodic observation cycle execution | 🟢 VERIFIED |

---

## 3. Platform Configuration & Safety Audit

The configuration in [`app/config/settings.py`](file:///c:/SentinelScale/services/platform/app/config/settings.py) was audited for correctness and safety:

- **Telemetry Provider Selection:** `TELEMETRY_PROVIDER = "mock"` (development default; selectable to `prometheus`, `kubernetes`, or `hybrid`).
- **Prometheus URL:** `PROMETHEUS_URL = "http://prometheus:9090"`, timeout `5.0s`, query window `1m`.
- **Kubernetes Settings:** In-cluster ServiceAccount token discovery + fallback to `KUBERNETES_API_URL` with TLS verification.
- **Safety Invariants (Strict Guarantee):**
  - `SENTINEL_DRY_RUN = True`
  - `SENTINEL_SHADOW_MODE = True`
  - `SENTINEL_AUTONOMOUS_ACTIONS_ENABLED = False`
  - **Kubernetes Mutations = 0** (explicit test in `test_decision_engine.py` asserts absence of mutating clients or subprocess commands).
- **Default Capacity Parameters:**
  - `DEFAULT_POD_RPS_CAPACITY = 350.0`
  - `DEFAULT_MIN_PODS = 2`
  - `DEFAULT_MAX_PODS = 20`
  - `DEFAULT_TARGET_CPU_UTILIZATION = 0.70`
- **F2 Accumulator Thresholds:**
  - `DEMAND_OBSERVATION_MAX_RISK = 0.80`
  - `DEMAND_OBSERVATION_MIN_LEGITIMACY = 0.20`
  - `DEMAND_OBSERVATION_MIN_CONFIDENCE = 0.30`

---

## 4. Telemetry Provider Architecture Verification

The Platform supports four pluggable telemetry providers implementing the abstract `ResourceTelemetryProvider` interface:

1. **`MockTelemetryProvider`**: Generates deterministic synthetic `ResourceState` for isolated testing.
2. **`PrometheusTelemetryProvider`**: Queries Prometheus `/api/v1/query` with PromQL expressions for request rate, P95 latency, 5xx error rate, CPU utilization, and memory utilization.
3. **`KubernetesTelemetryProvider`**: Queries Kubernetes API directly for Deployment replica specs and active Pod container resource requests/limits.
4. **`HybridTelemetryProvider`**: Composes Kubernetes infrastructure limits as normalization denominators for live Prometheus runtime telemetry queries.

---

## 5. Frozen Contract Conformance

All 5 frozen JSON Schemas (`v1.0.0`) remain strictly synchronized:
- `contracts/traffic/traffic_assessment.schema.json`
- `contracts/demand/demand_forecast.schema.json`
- `contracts/resources/resource_state.schema.json`
- `contracts/decisions/decision_context.schema.json`
- `contracts/decisions/scaling_decision.schema.json`

Zero schema or model changes were made.

---

## 6. Test Suite Verification

### Isolated Test Runner (`python run_tests.py`):
- **Demo API:** 9 passed, 0 failed
- **Traffic Intelligence (M1):** 5 passed, 0 failed
- **Demand Intelligence (M2):** 100 passed, 0 failed
- **Platform & Decision Engine (M3):** 242 passed, 2 skipped, 0 failed
- **Total:** **356 passed, 2 skipped, 0 failed**

*Note on Skipped Tests:*
- `test_prometheus_live_integration.py`: Skipped when external Prometheus server is not running on `localhost:9090`.
- `test_traffic_harness_live.py`: Skipped when live services are not active on `:8000` and `:8001` (executes and passes during live multi-process validation).

---

## 7. Known Baseline Limitations

1. **Local Testbed Telemetry:** Local standalone test runs default to `MockTelemetryProvider` for infrastructure telemetry; live Prometheus server on `localhost:9090` is required for live Prometheus queries.
2. **No Actuation by Design:** The platform operates strictly in shadow mode / dry run mode (`SENTINEL_DRY_RUN=True`), producing recommendations without mutating cluster state.
3. **No External ML Dependencies:** Module 3 uses deterministic statistical heuristics and OLS linear trend fitting rather than heavy ML packages.

---

## 8. Exact Next Step: M3-1 Prometheus Live Observability

The platform baseline is complete, hardened, and verified.
The next planned stage is **M3-1: Prometheus Live Observability Integration**, which will validate live PromQL queries, metric scrape endpoints, and live Prometheus telemetry provider execution against running containers.

