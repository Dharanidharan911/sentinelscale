# SentinelScale Stage M3-9: OpenTelemetry Foundation & Distributed Tracing

## 1. Objective & Overview

Stage **M3-9** establishes a **production-grade OpenTelemetry observability foundation** for SentinelScale. It introduces distributed tracing, W3C TraceContext (`traceparent`) propagation across HTTP service boundaries, trace-to-log correlation in structured JSON logs, and standard OpenTelemetry Collector ingestion across both Docker Compose and Kubernetes deployment runtimes.

The primary goals of M3-9:
1. **End-to-End Distributed Traceability**: Propagate standardized W3C `traceparent` contexts across inter-service calls (`Platform` → `Traffic Intelligence`, `Platform` → `Demand Intelligence`).
2. **Contextual Observability Spans**: Emit fine-grained observational spans across key architectural boundaries (`ContextAggregatorService`, `DecisionEngine`, and HTTP clients).
3. **Trace-to-Log Correlation**: Enrich all structured JSON logs with active `otel_trace_id` (32-hex) and `otel_span_id` (16-hex) alongside the legacy business `trace_id`.
4. **Resilient Non-Blocking Lifecycle**: OpenTelemetry initialization is fail-safe; network/collector unreachability never impacts HTTP request handling or decision evaluation.
5. **OpenTelemetry Collector Standard Ingestion**: Deploy collector configurations supporting OTLP over gRPC (4317) and HTTP (4318) for Docker Compose and Kubernetes.

---

## 2. Distributed Tracing Architecture

```text
Incoming HTTP Request (FastAPI)
         │  (W3C TraceContext extracted or root span created)
         ▼
[StructuredLoggingMiddleware] ──► Sets X-OTel-Trace-ID & Enriches JSON Logs
         │
         ▼
[ContextAggregatorService.aggregate_context]
         │
         ├──► [TrafficIntelligenceClient] ──(HTTP POST + W3C traceparent)──► [Module 1: Traffic Intelligence]
         │
         ├──► [DemandIntelligenceClient]  ──(HTTP POST + W3C traceparent)──► [Module 2: Demand Intelligence]
         │
         └──► [ResourceObserverService]   ──(Prometheus / K8s Client)────► [Cluster Telemetry]
         │
         ▼
[DecisionEngine.evaluate_decision] ──► (Span: action, confidence, recommendations)
         │
         ▼
[OpenTelemetry SDK: BatchSpanProcessor]
         │  (Async non-blocking OTLP HTTP / gRPC export)
         ▼
[OpenTelemetry Collector] (Docker Compose / Kubernetes)
         │
         ├──► Debug / Standard Exporters
         └──► Observability Backend (Prometheus / Grafana)
```

---

## 3. Implementation Details

### 3.1 OpenTelemetry Core Module (`services/platform/app/telemetry/tracing.py`)
- **`init_tracing()`**: Initializes the `TracerProvider`, `Resource` metadata (`service.name`, `service.version`, `deployment.environment`), sampling rules (`TraceIdRatioBased`), and `BatchSpanProcessor` with `OTLPSpanExporter`.
- **`shutdown_tracing()`**: Gracefully flushes and closes active span processors.
- **`create_span()`**: Context manager creating observational spans, recording semantic attributes, capturing exceptions, and assigning `StatusCode.ERROR` on failure.
- **`inject_trace_context(headers)` / `extract_trace_context(headers)`**: Injects and extracts W3C `traceparent` headers using `TraceContextTextMapPropagator`.
- **`get_current_trace_id()` / `get_current_span_id()`**: Extracts active hexadecimal trace and span IDs.

### 3.2 Structured Logging Correlation (`services/platform/app/logging.py`)
- **`JsonFormatter`**: Automatically inspects the active OpenTelemetry context and injects `otel_trace_id` and `otel_span_id` into every structured log entry.
- **`StructuredLoggingMiddleware`**: Emits `X-OTel-Trace-ID` and `X-Trace-ID` in HTTP response headers for external tracing correlation.

### 3.3 HTTP Clients Instrumentation
- **`TrafficIntelligenceClient`**: Automatically injects W3C `traceparent` header into outbound requests to Module 1 and creates client span `traffic_intelligence.fetch_assessment`.
- **`DemandIntelligenceClient`**: Automatically injects W3C `traceparent` header into outbound requests to Module 2 and creates client span `demand_intelligence.fetch_forecast`.

### 3.4 OpenTelemetry Collector Manifests
- **Docker Compose**: Service `otel-collector` using `otel/opentelemetry-collector-contrib:0.96.0` mapped to ports `4317` and `4318`.
- **Kubernetes Manifests (`infrastructure/kubernetes/otel-collector/`)**:
  - `configmap.yaml`: Collector configuration with OTLP receivers, health check extension (`:13133`), batch processor, and debug exporter.
  - `deployment.yaml`: Single replica collector deployment with standard liveness/readiness probes.
  - `service.yaml`: `ClusterIP` service exposing ports `4317` (gRPC), `4318` (HTTP), and `13133` (health check).

---

## 4. Safety Invariants & Preserved Boundaries

1. **Zero Kubernetes Scaling Mutations**: SentinelScale strictly maintains `dry_run=True`, `shadow_mode=True`, and `SENTINEL_AUTONOMOUS_ACTIONS_ENABLED=False`.
2. **Contract Immutability**: All JSON Schemas under `contracts/` remain frozen at `v1.0.0`.
3. **Observability Isolation**: Distributed tracing is purely observational. SDK initialization or exporter network failures degrade gracefully to no-op.
4. **Member Branch Isolation**: No code or business logic modified in Member 1 (`services/traffic-intelligence`) or Member 2 (`services/demand-intelligence`).

---

## 5. Automated Test Coverage & Verification

Stage M3-9 adds dedicated automated unit and integration tests in `services/platform/tests/test_opentelemetry_tracing.py`:
- TracerProvider lifecycle, disabled/enabled state transitions, and custom samplers.
- W3C `traceparent` injection and extraction.
- Observational span creation, custom attribute recording, and exception status capture.
- Structured JSON log correlation with active span context.
- HTTP client outbound W3C header injection.
- DecisionEngine evaluation span instrumentation.
- OpenTelemetry Collector configuration and Kubernetes manifest schema validation.

### Test Suite Execution Summary
```text
======================================================================
 SentinelScale Subprocess-Isolated Microservice Test Runner
======================================================================
 - Demo API                            : 9 PASSED
 - Traffic Intelligence                : 5 PASSED
 - Demand Intelligence                 : 100 PASSED
 - Platform & Decision Engine          : 305 PASSED (2 skipped)
======================================================================
 ALL 4 SERVICE TEST SUITES PASSED SUCCESSFULLY (419 passed, 2 skipped)
======================================================================
```
