# Module 3: Platform, Resource Intelligence & Decision Engine

The Platform service (`services/platform`) is responsible for observing infrastructure telemetry, evaluating policy-guarded capacity scaling decisions, comparing recommendations against traditional Kubernetes Horizontal Pod Autoscaler (HPA) baselines, and maintaining closed-loop observability.

---

## Telemetry Provider Architecture (Phase 1B)

The **Resource Observer** delegates metric collection to a pluggable `ResourceTelemetryProvider` interface. In Phase 1B, the production-grade `PrometheusTelemetryProvider` communicates with Prometheus to extract live request throughput, P95 latencies, error ratios, and normalized resource utilization ratios.

```
ResourceObserverService
          │ (delegates state retrieval)
          ▼
ResourceTelemetryProvider (ABC)
   ├── MockTelemetryProvider        <-- Active default (local dev & tests)
   ├── PrometheusTelemetryProvider  <-- Active in Phase 1B (real Prometheus telemetry)
   └── KubernetesTelemetryProvider  <-- Scheduled (Phase 2 Kubernetes integration)
```

---

## ResourceState Field Mapping & Telemetry Provenance

Every field in the canonical [`ResourceState`](file:///C:/SentinelScale/contracts/resources/resource_state.schema.json) contract has an explicit source and classification:

| Field | Category | Provenance & Formulation |
| :--- | :--- | :--- |
| `event_id` | **Metadata** | Unique UUIDv4 generated per observation event |
| `trace_id` | **Metadata** | Distributed trace ID propagated or generated (`trace-<hex>`) |
| `timestamp` | **Metadata** | ISO-8601 observation timestamp (`datetime.now(timezone.utc)`) |
| `contract_version` | **Metadata** | Contract schema version (`settings.CONTRACT_VERSION = "1.0.0"`) |
| `service_version` | **Metadata** | Platform service version (`settings.SERVICE_VERSION = "0.1.0"`) |
| `target_namespace` | **Metadata** | Target Kubernetes namespace (`sentinelscale`) |
| `target_workload` | **Metadata** | Target deployment identifier (`demo-api`) |
| `request_rate` | **Real Telemetry** | PromQL: `sum(rate(http_requests_total[1m]))` (RPS) |
| `p95_latency_ms` | **Real Telemetry** | PromQL: `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[1m])) by (le)) * 1000` |
| `error_rate` | **Real Telemetry** | PromQL: `sum(rate(http_requests_total{status=~"5.."}[1m])) / sum(rate(http_requests_total[1m]))` ($0.0 - 1.0$) |
| `cpu_utilization` | **Real Telemetry** | PromQL: `sum(rate(container_cpu_usage_seconds_total[1m])) / cpu_limit_cores` ($0.0 - 1.0$ normalized ratio) |
| `memory_utilization`| **Real Telemetry** | PromQL: `sum(container_memory_working_set_bytes) / memory_limit_bytes` ($0.0 - 1.0$ normalized ratio) |
| `running_pods` | *Configuration Assumption* | Documented Phase 1B baseline (`DEFAULT_BASELINE_RUNNING_PODS = 4`); Phase 2 Kubernetes provider will supply real pod state |
| `desired_pods` | *Configuration Assumption* | Documented Phase 1B baseline (`4` pods); Phase 2 Kubernetes provider |
| `pending_pods` | *Configuration Assumption* | Documented Phase 1B baseline (`0` pods); Phase 2 Kubernetes provider |
| `cpu_requested_cores` | *Configuration Assumption* | Documented Phase 1B baseline (`4.0` cores); Phase 2 Kubernetes provider |
| `cpu_limit_cores` | *Configuration Assumption* | Documented Phase 1B baseline (`8.0` cores); Phase 2 Kubernetes provider |
| `memory_requested_bytes` | *Configuration Assumption* | Documented Phase 1B baseline (`4 GiB`); Phase 2 Kubernetes provider |
| `memory_limit_bytes` | *Configuration Assumption* | Documented Phase 1B baseline (`8 GiB`); Phase 2 Kubernetes provider |
| `current_capacity_rps` | **Derived Metric** | `running_pods * DEFAULT_POD_RPS_CAPACITY` |
| `estimated_required_capacity_rps`| **Derived Metric** | `max(request_rate, 1.0)` |
| `estimated_resource_waste` | **Derived Metric** | $\max\left(0.0, \min\left(1.0, \frac{\text{current\_capacity\_rps} - \text{request\_rate}}{\text{current\_capacity\_rps}}\right)\right)$ (dimensionless ratio, not monetary cost) |

---

## Configuration

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `TELEMETRY_PROVIDER` | `mock` | Selected provider: `mock` \| `prometheus` |
| `PROMETHEUS_URL` | `http://prometheus:9090` | Upstream Prometheus HTTP API URL |
| `PROMETHEUS_TIMEOUT_SECONDS` | `5.0` | HTTP query timeout |
| `PROMETHEUS_QUERY_WINDOW` | `1m` | PromQL rate aggregation time window |
| `DEFAULT_POD_RPS_CAPACITY` | `350.0` | Configured baseline capacity assumption per container replica |
| `SENTINEL_DRY_RUN` | `true` | Enforces recommendation-only mode (no mutating actions) |
| `SENTINEL_SHADOW_MODE` | `true` | Enforces baseline HPA divergence comparison |

---

## Failure Handling & Observability

- **Explicit Failures**: When `TELEMETRY_PROVIDER=prometheus` and Prometheus is unreachable or queries fail, `PrometheusTelemetryProvider` raises `TelemetryProviderError`.
- **No Silent Fallbacks**: Automatic fallback to mock telemetry is strictly disabled in production mode.
- **HTTP Gateway Mapping**: `TelemetryProviderError` is surfaced as **HTTP 502 Bad Gateway** at `/api/v1/resources/current` with structured logging.

---

## Local Verification with Live Prometheus

To verify Prometheus integration with Docker Compose:

```bash
# 1. Start the stack (demo-api, prometheus, platform)
docker-compose up -d demo-api prometheus

# 2. Generate sample traffic on demo-api to populate metrics
curl http://localhost:8000/products
curl http://localhost:8000/products/prod-001
curl http://localhost:8000/search?q=security

# 3. Query platform with Prometheus provider enabled
TELEMETRY_PROVIDER=prometheus PROMETHEUS_URL=http://localhost:9090 uvicorn app.main:app --port 8003

# 4. In a separate terminal, fetch resource state
curl http://localhost:8003/api/v1/resources/current
```

### Example Response:
```json
{
  "event_id": "a93f18b3-76ef-46c9-83bc-e3621da3b3bc",
  "trace_id": "trace-419b48acde127",
  "timestamp": "2026-09-01T00:50:00.000000Z",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "target_namespace": "sentinelscale",
  "target_workload": "demo-api",
  "cpu_utilization": 0.125,
  "memory_utilization": 0.082,
  "cpu_requested_cores": 4.0,
  "cpu_limit_cores": 8.0,
  "memory_requested_bytes": 4294967296,
  "memory_limit_bytes": 8589934592,
  "running_pods": 4,
  "desired_pods": 4,
  "pending_pods": 0,
  "request_rate": 45.2,
  "p95_latency_ms": 12.8,
  "error_rate": 0.0,
  "current_capacity_rps": 1400.0,
  "estimated_required_capacity_rps": 45.2,
  "estimated_resource_waste": 0.9677
}
```
