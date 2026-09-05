# Stage M3-1 — Prometheus Live Observability Integration Report

> **Live validation of Prometheus telemetry ingestion, PromQL resource signals, and Prometheus-backed DecisionContext evaluation.**

---

## 1. Executive Summary

Stage M3-1 establishes and verifies the live Prometheus observability integration for **SentinelScale Member 3 (Platform & Decision Engine)**.

Prior to M3-1, `PrometheusTelemetryProvider` existed and was unit-tested with mock HTTP clients, but was not live-verified against an active Prometheus instance during F6. Stage M3-1 launched an official Prometheus v2.50.1 server, validated metric scraping across local and container endpoints on `/metrics`, verified real-time PromQL query execution, and validated the complete decision pipeline driven by live Prometheus telemetry.

---

## 2. What Existed Before M3-1 vs. What Was Changed

| Dimension | Before M3-1 | M3-1 Implementation |
| :--- | :--- | :--- |
| **Prometheus Scrape Config** | Scraped container DNS targets (`demo-api:8000`, etc.) | Added dual local development targets (`127.0.0.1:8000`, `localhost:8000`, etc.) in [`telemetry/prometheus/prometheus.yml`](file:///c:/SentinelScale/telemetry/prometheus/prometheus.yml) with 2s scrape intervals |
| **Prometheus Server** | Inactive in local runs (`test_prometheus_live_integration.py` skipped) | Official Prometheus v2.50.1 running live on `http://localhost:9090` |
| **Telemetry Provider** | Defaulted to `MockTelemetryProvider` | Verified `TELEMETRY_PROVIDER=prometheus` against live `/api/v1/query` endpoint |
| **PromQL Queries** | Tested with synthetic JSON responses | Executed live instant PromQL queries for `http_requests_total`, `process_cpu_seconds_total`, and latency buckets |
| **Decision Flow** | Tested with mock `ResourceState` | Validated live `ResourceState` -> `DecisionContext` -> `DecisionEngine` -> `ScalingDecision` |
| **Test Suite Baseline** | 356 passed, 2 skipped | **357 passed, 1 skipped** (`test_prometheus_live_integration.py` passed live) |

---

## 3. Scrape Configuration & Endpoints

Scrape configuration located in [`telemetry/prometheus/prometheus.yml`](file:///c:/SentinelScale/telemetry/prometheus/prometheus.yml):

```yaml
global:
  scrape_interval: 2s
  evaluation_interval: 2s

scrape_configs:
  - job_name: 'sentinelscale-services'
    metrics_path: '/metrics'
    static_configs:
      - targets:
          - 'demo-api:8000'
          - 'traffic-intelligence:8001'
          - 'demand-intelligence:8002'
          - 'platform:8003'
          - '127.0.0.1:8000'
          - '127.0.0.1:8001'
          - '127.0.0.1:8002'
          - '127.0.0.1:8003'
          - 'localhost:8000'
          - 'localhost:8001'
          - 'localhost:8002'
          - 'localhost:8003'
        labels:
          environment: 'development'
          cluster: 'sentinelscale-local'
```

### Monitored Service Metrics Endpoints:
- `demo-api`: Exposes `/metrics` with `http_requests_total`, `http_request_duration_seconds_bucket`, `process_cpu_seconds_total`, `process_resident_memory_bytes`.
- `platform`: Exposes `/metrics` with operational platform counters (`sentinelscale_scaling_decisions_total`, etc.).

---

## 4. PromQL Resource Signals

The `PrometheusTelemetryProvider` in [`services/platform/app/services/telemetry/prometheus_provider.py`](file:///c:/SentinelScale/services/platform/app/services/telemetry/prometheus_provider.py) maps the following PromQL expressions into canonical `ResourceState`:

| Metric Signal | PromQL Query Expression | ResourceState Mapping |
| :--- | :--- | :--- |
| **Request Rate (RPS)** | `sum(rate(http_requests_total[1m])) or sum(rate(http_requests_total{job="sentinelscale-services"}[1m]))` | `ResourceState.request_rate` |
| **P95 Latency (ms)** | `(histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[1m])) by (le)) * 1000) or ((sum(rate(http_request_duration_seconds_sum[1m])) / sum(rate(http_request_duration_seconds_count[1m]))) * 1000)` | `ResourceState.p95_latency_ms` |
| **5xx Error Rate** | `sum(rate(http_requests_total{status=~"5.."}[1m])) / sum(rate(http_requests_total[1m]))` | `ResourceState.error_rate` |
| **CPU Utilization** | `sum(rate(container_cpu_usage_seconds_total{container=~".*demo-api.*"}[1m])) or sum(rate(process_cpu_seconds_total[1m]))` divided by `cpu_limit_cores` | `ResourceState.cpu_utilization` |
| **Memory Utilization** | `sum(container_memory_working_set_bytes{container=~".*demo-api.*"}) or sum(process_resident_memory_bytes)` divided by `memory_limit_bytes` | `ResourceState.memory_utilization` |

---

## 5. Live Provenance & Decision Evaluation Evidence

### Live Chain Trace:
```
Real HTTP GET /products Requests
        │
        ▼
   Demo API :8000
        │ (recorded in _request_counts and _duration_sums)
        ▼
   GET /metrics
        │ (scraped every 2s by Prometheus)
        ▼
   Prometheus Server :9090
        │
        ▼ (POST /api/v1/query with PromQL)
   PrometheusTelemetryProvider
        │ (constructed canonical ResourceState: CPU=0.0023, Mem=0.0156, Pods=4)
        ▼
   DecisionContext
        │ (combined with TrafficAssessment + DemandForecast)
        ▼
   DecisionEngine
        │ (evaluated ScalingDecision: Action=SCALE, Current=4, Desired=2)
        ▼
   HPAEvaluationService
        │ (Category=ALIGNED, Replica Delta=0, Pod-Hours Saved=0.0)
        ▼
   EvaluationResult
```

### Live Validation Output Captured:
```text
1. Live Prometheus ResourceState: demo-api | CPU Util: 0.0023 | Mem Util: 0.0156 | Pods: 4
2. ScalingDecision with Live Prometheus Data:
   - Action: SCALE
   - Current Pods: 4 | Recommended Pods: 2
   - Baseline HPA Pods: 2
   - DryRun: True | ShadowMode: True
3. Comparative HPA Evaluation:
   - Category: ALIGNED
   - Replica Delta: 0
   - Pod-Hours Saved: 0.0
```

---

## 6. Telemetry Provider Selection Verification

The platform supports runtime provider selection via environment variable `TELEMETRY_PROVIDER`:

```powershell
# 1. Select Live Prometheus
$env:TELEMETRY_PROVIDER = "prometheus"
$env:PROMETHEUS_URL = "http://localhost:9090"

# 2. Select Mock Provider (for offline tests)
$env:TELEMETRY_PROVIDER = "mock"

# 3. Select Kubernetes Provider
$env:TELEMETRY_PROVIDER = "kubernetes"

# 4. Select Hybrid Provider
$env:TELEMETRY_PROVIDER = "hybrid"
```

The factory in [`app/services/telemetry/factory.py`](file:///c:/SentinelScale/services/platform/app/services/telemetry/factory.py) instantiates the appropriate class without altering downstream service interfaces or data contracts.

---

## 7. Safety Invariants & Boundary Rules

1. **`dry_run=True`**: All decisions are emitted as non-actuating recommendations.
2. **`shadow_mode=True`**: Active across all evaluations.
3. **`autonomous_actions_enabled=False`**: Active by default.
4. **`Kubernetes mutations = 0`**: Zero mutation calls (`kubectl`, `PATCH /scale`) exist in the execution path.

---

## 8. Test Execution Summary

- **Platform Test Suite:** **243 passed, 1 skipped** (`test_prometheus_live_integration.py` PASSED live against `:9090`).
- **Full Multi-Service Test Runner (`python run_tests.py`):**
  - Demo API: **9 passed**
  - Traffic Intelligence: **5 passed**
  - Demand Intelligence: **100 passed**
  - Platform & Decision Engine: **243 passed (1 skipped)**
  - **Total: 357 passed, 1 skipped, 0 failed**

---

## 9. Known Limitations

1. **Host-Based Container Simulation:** When running Prometheus natively on host without full container cgroups, CPU and memory utilization are extracted from process-level counters (`process_cpu_seconds_total` and `process_resident_memory_bytes`) rather than container-level cgroup metrics (`container_cpu_usage_seconds_total`).
2. **Shadow Execution Only:** The platform does not alter live Prometheus alerts or trigger upstream gateway rate limiting.

