# SentinelScale Stage M3-6: Kubernetes Resource Intelligence

## 1. Objective & Overview

Stage **M3-6** establishes **Kubernetes Resource Intelligence** for SentinelScale. It equips the Platform service with the capability to query the Kubernetes REST API to observe and normalize real-time infrastructure resource state for target workloads into the canonical, frozen `ResourceState` schema (`contracts/resources/resource_state.schema.json`).

M3-6 answers the fundamental question:
> **What is the current Kubernetes resource state of the workload SentinelScale is evaluating?**

---

## 2. Telemetry Provider Architecture & Data Provenance

SentinelScale cleanly decouples Kubernetes infrastructure specifications from Prometheus runtime telemetry:

```text
                    ┌─────────────────────────┐
                    │  Kubernetes REST API    │
                    │  (Deployment, Pods)     │
                    └────────────┬────────────┘
                                 │
                desired_pods, running_pods, pending_pods,
                cpu_requested/limit, memory_requested/limit
                                 │
                                 ▼
                     KubernetesTelemetryProvider
                                 │
                                 ├────────────────────────┐
                                 │                        │
                    (k8s limit denominators)              │
                                 ▼                        │
                    PrometheusTelemetryProvider           │
                                 │                        │
                      cpu_utilization, mem_util,          │
                      request_rate, p95_lat, error_rate   │
                                 │                        │
                                 ▼                        ▼
                     HybridTelemetryProvider ─────────────┘
                                 │
                        ResourceState (v1.0.0)
                                 │
                                 ▼
                      ContextAggregatorService
                                 │
                                 ▼
                          DecisionEngine
```

### 2.1 Provenance Breakdown

| Metric / Field | Data Source | Collection Mechanism |
| :--- | :--- | :--- |
| `desired_pods` | Kubernetes API | `GET /apis/apps/v1/namespaces/{ns}/deployments/{workload}` (`spec.replicas`) |
| `running_pods`, `pending_pods` | Kubernetes API | `GET /api/v1/namespaces/{ns}/pods?labelSelector=...` (phase counting) |
| `cpu_requested_cores`, `cpu_limit_cores` | Kubernetes API | Aggregated across active pod container specs parsed via `parse_cpu_quantity` |
| `memory_requested_bytes`, `memory_limit_bytes` | Kubernetes API | Aggregated across active pod container specs parsed via `parse_memory_quantity` |
| `cpu_utilization`, `memory_utilization` | Prometheus | Real PromQL rate queries normalized by Kubernetes limit denominators |
| `request_rate`, `p95_latency_ms`, `error_rate` | Prometheus | Real PromQL rate, histogram percentile, and 5xx error rate queries |
| `current_capacity_rps`, `estimated_resource_waste` | Platform Model | Deterministic mathematical derivation ($\text{running\_pods} \times \text{DEFAULT\_POD\_RPS\_CAPACITY}$) |

---

## 3. Quantity Parsing & Normalization

Kubernetes resource strings are parsed into standard floating-point cores and integer bytes via [`services/platform/app/services/telemetry/quantity_parser.py`](../services/platform/app/services/telemetry/quantity_parser.py):

### CPU Quantity Parsing
- Millicores: `"100m"` $\to 0.1$, `"500m"` $\to 0.5$, `"1500m"` $\to 1.5$
- Plain / Decimal Cores: `"1"` $\to 1.0$, `"0.5"` $\to 0.5$, `2` $\to 2.0$

### Memory Quantity Parsing
- Binary SI ($1024^n$): `"64Ki"` ($65,536$), `"128Mi"` ($134,217,728$), `"256Mi"` ($268,435,456$), `"1Gi"` ($1,073,741,824$)
- Decimal SI ($1000^n$): `"100k"` ($100,000$), `"500M"` ($500,000,000$), `"2G"` ($2,000,000,000$)
- Integer Bytes: `"1048576"` ($1,048,576$)

---

## 4. RBAC Minimum-Privilege Verification

The Platform service operates with strictly read-only permissions via ServiceAccount `sentinelscale-platform`:

```text
kubectl auth can-i get deployments    --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> YES
kubectl auth can-i list deployments   --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> YES
kubectl auth can-i get pods          --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> YES
kubectl auth can-i list pods         --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> YES

kubectl auth can-i create deployments --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> NO
kubectl auth can-i update deployments --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> NO
kubectl auth can-i patch deployments  --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> NO
kubectl auth can-i delete pods        --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> NO
```

---

## 5. Live Cluster Evidence

Queried directly against the live `demo-api` workload in namespace `sentinelscale`:

### Live `ResourceState` JSON Output
```json
{
  "event_id": "3fe7d1d9-2174-4c04-90c9-69f04d2e2a2d",
  "trace_id": "trace-c98d474b736642cb",
  "timestamp": "2026-09-05T19:35:57.426252+00:00",
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "target_namespace": "sentinelscale",
  "target_workload": "demo-api",
  "cpu_utilization": 0.0029,
  "memory_utilization": 0.1016,
  "cpu_requested_cores": 0.2,
  "cpu_limit_cores": 1.0,
  "memory_requested_bytes": 268435456,
  "memory_limit_bytes": 536870912,
  "running_pods": 2,
  "desired_pods": 2,
  "pending_pods": 0,
  "request_rate": 0.31,
  "p95_latency_ms": 4.75,
  "error_rate": 0.0,
  "current_capacity_rps": 700.0,
  "estimated_required_capacity_rps": 1.0,
  "estimated_resource_waste": 0.9996
}
```

---

## 6. Safety Invariants & Boundary Rules

- `dry_run = True`
- `shadow_mode = True`
- `SENTINEL_AUTONOMOUS_ACTIONS_ENABLED = False`
- **Zero Kubernetes Scaling Mutations**: No replica modifications, no HPA resources created, no deployment patching.
- **Frozen Contracts**: All 5 v1.0.0 JSON Schemas in `contracts/` remain strictly unmodified.

---

## 7. Automated Test Results

```text
======================================================================
 TEST EXECUTION SUMMARY
======================================================================
 - Demo API                            : PASSED (9 passed)
 - Traffic Intelligence                : PASSED (5 passed)
 - Demand Intelligence                 : PASSED (100 passed)
 - Platform & Decision Engine          : PASSED (286 passed, 2 skipped)
======================================================================
 ALL 4 SERVICE TEST SUITES PASSED SUCCESSFULLY (400 passed, 2 skipped)
======================================================================
```

---

## 8. Relationship to Next Stages

- **Stage M3-6** establishes live Kubernetes resource observation and normalization.
- **Stage M3-7** will integrate real Kubernetes Horizontal Pod Autoscaler (HPA) telemetry and comparison.
- **Stage M3-8** will execute comparative HPA vs. SentinelScale attack experimentation.
