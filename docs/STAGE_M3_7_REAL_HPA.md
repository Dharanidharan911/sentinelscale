# SentinelScale Stage M3-7: Real Kubernetes HPA Baseline Controller

## 1. Objective & Overview

Stage **M3-7** establishes a **real, native Kubernetes Horizontal Pod Autoscaler (`autoscaling/v2`)** for the target workload (`demo-api`) in namespace `sentinelscale`.

The objective of M3-7 is to create an authentic, observable **baseline scaling controller** governed directly by the Kubernetes control plane. This establishes the foundational empirical baseline against which SentinelScale's security-aware, predictive decision intelligence is comparatively evaluated.

### Core Architectural Invariant
- **Kubernetes HPA** is the external, native infrastructure autoscaler that acts upon CPU metrics (`metrics-server`).
- **SentinelScale Platform** remains strictly an **observer and decision intelligence engine** (`dry_run=True`, `shadow_mode=True`, `SENTINEL_AUTONOMOUS_ACTIONS_ENABLED=False`). SentinelScale performs **0 Kubernetes scaling mutations**.

---

## 2. Infrastructure Setup & Metrics Server

### 2.1 Metrics Server Deployment
Docker Desktop Kubernetes (`v1.32.2`) runs single-node clusters with self-signed Kubelet certificates. To enable `metrics.k8s.io` aggregation:
1. Deployed the official `metrics-server` release (`v0.7.2`) in namespace `kube-system`.
2. Patched container args with `--kubelet-insecure-tls` and `--kubelet-preferred-address-types=InternalIP,ExternalIP,Hostname`.
3. Verified live node and pod metrics:
   ```bash
   kubectl top nodes
   # Output: docker-desktop CPU 961m, Memory 2293Mi
   kubectl top pods -n sentinelscale
   # Output: All 7 service pods reporting live CPU (m) and Memory (Mi)
   ```

### 2.2 HPA Manifest (`infrastructure/kubernetes/demo-api/hpa.yaml`)
Configured modern `autoscaling/v2` specification with conservative bounds and responsive stabilization windows:
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: demo-api-hpa
  namespace: sentinelscale
  labels:
    app.kubernetes.io/name: demo-api
    app.kubernetes.io/component: workload-autoscaler
    app.kubernetes.io/part-of: sentinelscale
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: demo-api
  minReplicas: 2
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 50
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      selectPolicy: Max
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 2
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 15
      selectPolicy: Max
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 2
          periodSeconds: 15
```

### 2.3 RBAC Permissions (`infrastructure/kubernetes/platform/rbac.yaml`)
Updated the Platform ServiceAccount role with strictly read-only access to HPA resources:
```yaml
- apiGroups: ["autoscaling"]
  resources: ["horizontalpodautoscalers"]
  verbs: ["get", "list"]
```
Verified with `kubectl auth can-i`:
- `get horizontalpodautoscalers`: **YES**
- `create / update / patch / delete horizontalpodautoscalers`: **NO**

---

## 3. Empirical Scale-Up and Scale-Down Validation

A realistic sustained workload was dispatched using the k6 load testing container targeting `http://host.docker.internal:8000` via service port-forward.

### 3.1 Load Profile & Execution
- **Profile**: `sustained` with `VU_SCALE=2.0` (peak 50 Virtual Users)
- **Duration**: 90 seconds
- **Total Requests**: 16,537 requests delivered
- **Throughput**: 183.7 req/s
- **Success Rate**: 100% (0 errors, 33,074 passed assertions)

### 3.2 Scaling Lifecycle Timeline & Metrics

| Phase | Timestamp (UTC) | CPU Utilization (Target 50%) | Active Pods | Deployment Status | HPA State / Condition |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Pre-Load (Baseline)** | `19:44:38` | **2% (2m)** | 2 | 2/2 Ready | `AbleToScale=True`, `TooFewReplicas` |
| **Load Ramp & Surge** | `19:45:20` | **195% - 244% (244m)** | 2 | 2/2 Ready | `AbleToScale=True`, `ScaleUpLimit` |
| **HPA Rescale Up** | `19:46:15` | **244%** | 4 | 4/4 Ready | `Normal SuccessfulRescale: New size: 4; reason: cpu resource utilization above target` |
| **Cooldown & Load End** | `19:46:36` | **3% (3m)** | 4 | 4/4 Ready | `Stabilization window active (15s)` |
| **HPA Rescale Down** | `19:47:20` | **3% (3m)** | 2 | 2/2 Ready | `Normal SuccessfulRescale: New size: 2; reason: All metrics below target` |

### 3.3 Kubernetes Event Log Verification
```text
Events:
  Type    Reason             Age   From                       Message
  ----    ------             ----  ----                       -------
  Normal  SuccessfulRescale  74s   horizontal-pod-autoscaler  New size: 4; reason: cpu resource utilization (percentage of request) above target
  Normal  SuccessfulRescale  14s   horizontal-pod-autoscaler  New size: 2; reason: All metrics below target
```

---

## 4. SentinelScale Live Shadow Observation

Throughout and immediately following the HPA scaling lifecycle, SentinelScale M3-6 resource intelligence and decision orchestrator were queried inside the Kubernetes cluster:

### 4.1 Live `ResourceState` (`GET /api/v1/resources/current`)
```json
{
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "target_namespace": "sentinelscale",
  "target_workload": "demo-api",
  "cpu_utilization": 0.0031,
  "memory_utilization": 0.1016,
  "cpu_requested_cores": 0.2,
  "cpu_limit_cores": 1.0,
  "memory_requested_bytes": 268435456,
  "memory_limit_bytes": 536870912,
  "running_pods": 2,
  "desired_pods": 2,
  "pending_pods": 0,
  "request_rate": 0.29,
  "p95_latency_ms": 4.75,
  "error_rate": 0.0,
  "current_capacity_rps": 700.0,
  "estimated_required_capacity_rps": 1.0,
  "estimated_resource_waste": 0.9996
}
```

### 4.2 Live `ScalingDecision` (`POST /api/v1/decision/orchestrate`)
```json
{
  "contract_version": "1.0.0",
  "service_version": "0.1.0",
  "model_version": "policy-rules-v0",
  "action": "SCALE",
  "reason": "Predicted legitimate demand (700.1 RPS) exceeds capacity (700.0 RPS). Scaling to 3 pods. (Within standard policy safety bounds.)",
  "confidence": 0.9,
  "traffic_risk": 0.79,
  "predicted_legitimate_rps": 700.0964,
  "current_capacity_rps": 700.0,
  "current_pods": 2,
  "recommended_pods": 3,
  "baseline_hpa_recommended_pods": 2,
  "pod_delta_vs_baseline": 1,
  "policy": "default-safe-guardrail-v1",
  "dry_run": true,
  "shadow_mode": true
}
```

---

## 5. Verification & Safety Summary

1. **Metrics Source**: Official `metrics-server` operational and serving `metrics.k8s.io` queries.
2. **HPA Controller**: Native Kubernetes HPA resource configured with `minReplicas=2`, `maxReplicas=5`, target 50% CPU.
3. **Controlled Scale-Up**: Scaled from 2 to 4 replicas when CPU exceeded 50% threshold.
4. **Controlled Scale-Down**: Scaled from 4 back to 2 replicas once load ceased and stabilization window elapsed.
5. **SentinelScale Safety**: `dry_run=True`, `shadow_mode=True`, 0 mutations applied by SentinelScale.
6. **Automated Testing**: Added `services/platform/tests/test_hpa_manifests.py`.
7. **Full Test Suite Baseline**: **403 passed, 2 skipped** across all 4 microservices.
