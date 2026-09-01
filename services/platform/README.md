# Module 3: Platform, Resource Intelligence & Decision Engine

The Platform service (`services/platform`) is responsible for observing infrastructure telemetry, evaluating policy-guarded capacity scaling decisions, comparing recommendations against traditional Kubernetes Horizontal Pod Autoscaler (HPA) baselines, and maintaining closed-loop observability.

---

## Telemetry Provider Architecture (Phase 2A)

The **Resource Observer** delegates metric collection to a pluggable `ResourceTelemetryProvider` interface. In Phase 2A, the production-grade `KubernetesTelemetryProvider` queries the official Kubernetes REST API to observe real Deployment replica configurations, Pod lifecycle phases, and aggregated container resource limits and requests.

```
ResourceObserverService
          │ (delegates state retrieval)
          ▼
ResourceTelemetryProvider (ABC)
   ├── MockTelemetryProvider        <-- Active default (local dev & tests)
   ├── PrometheusTelemetryProvider  <-- Active in Phase 1B (real Prometheus telemetry)
   └── KubernetesTelemetryProvider  <-- Active in Phase 2A (real Kubernetes API state)
```

---

## Kubernetes Resource Telemetry (Phase 2A)

### API Endpoints Queried:
1. **Deployment Specs**:
   - `GET /apis/apps/v1/namespaces/{namespace}/deployments/{workload}`
   - Extracts: `spec.replicas` (`desired_pods`), `spec.selector.matchLabels` (label selector), `spec.template.spec.containers` (container template fallback).
2. **Pod Lifecycle & Container State**:
   - `GET /api/v1/namespaces/{namespace}/pods?labelSelector={selector}`
   - Discriminate Pod Phases:
     - `Running` $\rightarrow$ `running_pods` (included in active resource aggregation).
     - `Pending` $\rightarrow$ `pending_pods` (scheduled / starting).
     - `Failed` / `Succeeded` / `Unknown` $\rightarrow$ excluded from running pod counts.
   - Resource Aggregation: Sums container CPU and memory requests and limits across all active target pods.

### Resource Quantity Parsing (`app.services.telemetry.quantity_parser`):
- **CPU**:
  - Millicores: `"100m"` $\rightarrow 0.1$, `"500m"` $\rightarrow 0.5$, `"1500m"` $\rightarrow 1.5$ cores.
  - Plain / Decimal cores: `"1"` $\rightarrow 1.0$, `"0.5"` $\rightarrow 0.5$, `"2"` $\rightarrow 2.0$ cores.
- **Memory**:
  - Binary SI: `"128Ki"` $\rightarrow 131,072$, `"256Mi"` $\rightarrow 268,435,456$, `"4Gi"` $\rightarrow 4,294,967,296$ bytes.
  - Decimal SI: `"500k"` $\rightarrow 500,000$, `"200M"` $\rightarrow 200,000,000$, `"2G"` $\rightarrow 2,000,000,000$ bytes.
  - Plain integer bytes: `"1048576"` $\rightarrow 1,048,576$ bytes.

---

## RBAC Requirements

The Platform service requires strictly **read-only**, namespace-scoped permissions defined in [`infrastructure/kubernetes/platform/rbac.yaml`](file:///C:/SentinelScale/infrastructure/kubernetes/platform/rbac.yaml):

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: sentinelscale-platform-reader
  namespace: sentinelscale
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]
```

---

## ResourceState Field Mapping & Provenance (Phase 2A)

| Field | Category | Provenance & Formulation |
| :--- | :--- | :--- |
| `event_id` | **Metadata** | Unique UUIDv4 generated per observation event |
| `trace_id` | **Metadata** | Distributed trace ID propagated or generated (`trace-<hex>`) |
| `timestamp` | **Metadata** | ISO-8601 observation timestamp (`datetime.now(timezone.utc)`) |
| `contract_version` | **Metadata** | Contract schema version (`settings.CONTRACT_VERSION = "1.0.0"`) |
| `service_version` | **Metadata** | Platform service version (`settings.SERVICE_VERSION = "0.1.0"`) |
| `target_namespace` | **Metadata** | Target Kubernetes namespace (`sentinelscale`) |
| `target_workload` | **Metadata** | Target deployment identifier (`demo-api`) |
| `running_pods` | **Real K8s State** | Count of actual target Pods in `Running` phase |
| `desired_pods` | **Real K8s State** | Deployment `spec.replicas` |
| `pending_pods` | **Real K8s State** | Count of actual target Pods in `Pending` phase |
| `cpu_requested_cores` | **Real K8s State** | Aggregated CPU requests across running target pod containers |
| `cpu_limit_cores` | **Real K8s State** | Aggregated CPU limits across running target pod containers |
| `memory_requested_bytes` | **Real K8s State** | Aggregated memory requests in bytes across running target pod containers |
| `memory_limit_bytes` | **Real K8s State** | Aggregated memory limits in bytes across running target pod containers |
| `request_rate` | *Traffic Baseline* | `0.0` (Provided by Prometheus telemetry in Phase 1B / Phase 2B) |
| `p95_latency_ms` | *Traffic Baseline* | `0.0` (Provided by Prometheus telemetry in Phase 1B / Phase 2B) |
| `error_rate` | *Traffic Baseline* | `0.0` (Provided by Prometheus telemetry in Phase 1B / Phase 2B) |
| `cpu_utilization` | *Traffic Baseline* | `0.0` (Provided by Prometheus telemetry in Phase 1B / Phase 2B) |
| `memory_utilization`| *Traffic Baseline* | `0.0` (Provided by Prometheus telemetry in Phase 1B / Phase 2B) |
| `current_capacity_rps` | **Derived Metric** | `running_pods * DEFAULT_POD_RPS_CAPACITY` |
| `estimated_required_capacity_rps`| **Derived Metric** | `max(request_rate, 1.0)` |
| `estimated_resource_waste` | **Derived Metric** | Overprovisioned capacity ratio |

---

## Configuration

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `TELEMETRY_PROVIDER` | `mock` | Selected provider: `mock` \| `prometheus` \| `kubernetes` |
| `KUBERNETES_API_URL` | `http://localhost:8001` | Kubernetes API Server base URL (when outside cluster) |
| `KUBERNETES_TOKEN` | `None` | Optional Bearer token for Kubernetes API authentication |
| `KUBERNETES_TIMEOUT_SECONDS` | `5.0` | Kubernetes API query timeout |
| `PROMETHEUS_URL` | `http://prometheus:9090` | Upstream Prometheus HTTP API URL |
| `DEFAULT_POD_RPS_CAPACITY` | `350.0` | Configured baseline capacity assumption per container replica |
| `SENTINEL_DRY_RUN` | `true` | Enforces recommendation-only mode (no mutating actions) |
| `SENTINEL_SHADOW_MODE` | `true` | Enforces baseline HPA divergence comparison |

---

## Local Verification with Live Kubernetes Cluster

To manually verify the Kubernetes provider against a local Kubernetes cluster (Docker Desktop, minikube, or kind):

```bash
# 1. Start local Kubernetes cluster and apply manifests
kubectl apply -f infrastructure/kubernetes/namespace.yaml
kubectl apply -f infrastructure/kubernetes/demo-api/deployment.yaml
kubectl apply -f infrastructure/kubernetes/demo-api/service.yaml
kubectl apply -f infrastructure/kubernetes/platform/rbac.yaml

# 2. Start Kubernetes API proxy locally on port 8001
kubectl proxy --port=8001

# 3. Start Platform service with Kubernetes provider enabled
$env:TELEMETRY_PROVIDER="kubernetes"
$env:KUBERNETES_API_URL="http://localhost:8001"
$env:PYTHONPATH="$PWD\services\platform"
python -m uvicorn app.main:app --port 8003

# 4. In a separate terminal, fetch observed Kubernetes resource state
curl http://localhost:8003/api/v1/resources/current?namespace=sentinelscale&workload=demo-api
```
