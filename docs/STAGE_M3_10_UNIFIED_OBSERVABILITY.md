# SentinelScale Stage M3-10: Unified Observability

## 1. Objective & Operational Flow

Stage **M3-10** unifies the three pillars of observability (**Metrics, Logs, and Traces**) into a seamless, interconnected operator experience in Grafana. It enables an operator to execute bidirectional, cross-signal drilldown across the entire SentinelScale lifecycle:

```text
       Metrics (Prometheus)
              │
              ▼ (Pre-filtered Service / Timestamp Query)
         Logs (Loki)
              │
              ▼ (derivedFields: otel_trace_id / trace_id)
        Traces (Tempo)
              │
              ▼ (Distributed Waterfall)
  Platform ➔ Traffic Intelligence / Demand Intelligence ➔ DecisionEngine
              │
              ▼ (tracesToLogs)
         Logs (Loki)
```

---

## 2. Unified Observability Components

### 2.1 Backend Ingestion & Storage
- **Prometheus (`prom/prometheus:v2.50.1` on `:9090`)**:
  - Scrapes metrics from `demo-api:8000` and `platform:8003` every 2s.
  - Computes request rates, error rates, latencies, and SentinelScale decision divergence metrics.
- **Tempo (`grafana/tempo:2.4.1` on `:3200` / `:4317`)**:
  - Ingests distributed OTLP spans from the OpenTelemetry Collector via gRPC (`tempo:4317`).
  - Indexes trace IDs, service names, and span tags with search enabled.
- **Loki (`grafana/loki:2.9.8` on `:3100`)**:
  - Ingests structured JSON logs from microservices with indexed labels (`service`, `level`, `endpoint`).
- **OpenTelemetry Collector (`otel/opentelemetry-collector-contrib:0.96.0` on `:4317`/`:4318`)**:
  - Ingests application spans and routes them directly to Tempo (`otlp/tempo` exporter on `tempo:4317`).

---

## 3. Grafana Cross-Signal Correlation Configuration

### 3.1 Datasource Provisioning
1. **Prometheus (`telemetry/grafana/provisioning/datasources/prometheus.yaml`)**:
   - Primary metrics engine for PromQL panels and threshold alerts.
2. **Tempo (`telemetry/grafana/provisioning/datasources/tempo.yaml`)**:
   - Configured with `tracesToLogs`: Automatically queries Loki for logs within the exact span timeframe matching `service.name` / `service`.
   - Integrated with `serviceMap` backed by Prometheus.
3. **Loki (`telemetry/grafana/provisioning/datasources/loki.yaml`)**:
   - Configured with `derivedFields`: Automatically extracts `otel_trace_id` (32-character hex) and legacy `trace_id`, generating a clickable **"View Tempo Trace"** badge directly in every log entry.

### 3.2 Provisioned Dashboards
1. **`SentinelScale — Infrastructure Observability` (`sentinelscale-infra-obs`)**:
   - Preserves all 8 canonical PromQL panels (Total RPS, Error Rate, P95 Latency, Scrape Availability, Endpoint Rates, Latency Distribution, CPU, Memory).
2. **`SentinelScale — Unified Observability` (`sentinelscale-unified-obs`)**:
   - **Row 1**: Executive Overview (SentinelScale Recommended Pods vs Reactive Baseline HPA Pods, Pod Divergence Delta, Traffic Security Risk Score).
   - **Row 2**: Comparative Decision Dynamics (Scaling Divergence Over Time, Workload RPS vs Predicted Legitimate Demand).
   - **Row 3**: Live Unified Log Stream (Loki stream with pre-configured `derivedFields` trace navigation).
   - **Row 4**: Distributed Trace Waterfall (Tempo trace search and span hierarchy view).

---

## 4. Safety Invariants & Preserved Boundaries

1. **`dry_run = True` and `shadow_mode = True`**:
   - Unconditionally preserved across all Platform evaluation paths.
   - Zero autonomous Kubernetes replica mutations.
2. **Contract Freezing**:
   - All schemas under `contracts/` remain frozen at `v1.0.0`.
3. **Team Isolation**:
   - Zero code modifications to Member 1 (`services/traffic-intelligence`) or Member 2 (`services/demand-intelligence`).
4. **Resilient Degradation**:
   - Observability backend availability never affects the execution or reliability of business endpoints.

---

## 5. Verification & Test Evidence

- **Automated Test Suite**: Added dedicated test suite [`services/platform/tests/test_unified_observability.py`](file:///c:/SentinelScale/services/platform/tests/test_unified_observability.py):
  - Validates all 3 datasource provisioning files (`prometheus.yaml`, `tempo.yaml`, `loki.yaml`).
  - Verifies `derivedFields` regular expressions and `tracesToLogs` mappings.
  - Validates dashboard schemas and panel types across both dashboards.
  - Validates Docker Compose and Kubernetes manifest definitions for Tempo and Loki.

### Full Test Execution Summary (`python run_tests.py`)
```text
======================================================================
 SentinelScale Subprocess-Isolated Microservice Test Runner
======================================================================
 - Demo API                            : 9 PASSED
 - Traffic Intelligence                : 5 PASSED
 - Demand Intelligence                 : 100 PASSED
 - Platform & Decision Engine          : 311 PASSED (2 skipped)
======================================================================
 ALL 4 SERVICE TEST SUITES PASSED SUCCESSFULLY (425 passed, 2 skipped)
======================================================================
```
