# SentinelScale Stage M3-5: Live Kubernetes

## 1. Overview & Objective

Stage **M3-5** transitions SentinelScale from Docker Compose to a **live, fully reproducible Kubernetes runtime** operating inside the `sentinelscale` namespace. It validates that the four core microservices (`demo-api`, `traffic-intelligence`, `demand-intelligence`, `platform`) alongside the observability layer (`prometheus`, `grafana`) operate with genuine Kubernetes DNS service discovery, non-root security contexts, health/readiness probes, real live Prometheus telemetry, k6 load testing, and controlled pod recovery.

---

## 2. Runtime Environment & Prerequisites

- **Host OS**: Windows 11 with Docker Desktop 4.43.2 (Engine v28.3.2)
- **Kubernetes Distribution**: Docker Desktop Kubernetes (`v1.32.2`)
- **Active Context**: `desktop-linux` (`docker-desktop` control-plane node)
- **Image Sharing Mechanism**: Docker Desktop Kubernetes shares the local Docker daemon container store directly; images tagged locally with `sentinelscale/<service>:v0.1.0` and `:latest` are resolved via `imagePullPolicy: IfNotPresent` without remote registry dependencies.

---

## 3. Kubernetes Resource Structure

All manifests reside in the canonical repository directory [`infrastructure/kubernetes/`](../infrastructure/kubernetes/):

```text
infrastructure/kubernetes/
├── namespace.yaml                       # Defines namespace 'sentinelscale'
├── demo-api/
│   ├── deployment.yaml                  # 2 replicas, port 8000, probes: /health, /ready
│   └── service.yaml                     # ClusterIP: demo-api:8000
├── traffic-intelligence/
│   ├── deployment.yaml                  # 1 replica, port 8001, probes: /health, /ready
│   └── service.yaml                     # ClusterIP: traffic-intelligence:8001
├── demand-intelligence/
│   ├── deployment.yaml                  # 1 replica, port 8002, probes: /health, /ready
│   └── service.yaml                     # ClusterIP: demand-intelligence:8002
├── platform/
│   ├── deployment.yaml                  # 1 replica, port 8003, emptyDir data volume
│   ├── service.yaml                     # ClusterIP: platform:8003
│   └── rbac.yaml                        # Read-only ServiceAccount, Role, RoleBinding
├── prometheus/
│   ├── configmap.yaml                   # 2s scrape interval for demo-api and platform
│   ├── deployment.yaml                  # prom/prometheus:v2.50.1, TSDB volume
│   └── service.yaml                     # ClusterIP: prometheus:9090
└── grafana/
    ├── configmaps.yaml                  # Datasource + dashboard definitions
    ├── deployment.yaml                  # grafana/grafana:10.4.1
    └── service.yaml                     # ClusterIP: grafana:3000
```

---

## 4. Image Build & Tagging Workflow

Deterministic local images are built directly from service Dockerfiles:

```powershell
docker build -t sentinelscale/demo-api:v0.1.0 -t sentinelscale/demo-api:latest ./demo-api
docker build -t sentinelscale/traffic-intelligence:v0.1.0 -t sentinelscale/traffic-intelligence:latest ./services/traffic-intelligence
docker build -t sentinelscale/demand-intelligence:v0.1.0 -t sentinelscale/demand-intelligence:latest ./services/demand-intelligence
docker build -t sentinelscale/platform:v0.1.0 -t sentinelscale/platform:latest ./services/platform
```

---

## 5. Deployment Commands

```powershell
kubectl apply -f infrastructure/kubernetes/namespace.yaml
kubectl apply -f infrastructure/kubernetes/prometheus/
kubectl apply -f infrastructure/kubernetes/grafana/
kubectl apply -f infrastructure/kubernetes/demo-api/
kubectl apply -f infrastructure/kubernetes/traffic-intelligence/
kubectl apply -f infrastructure/kubernetes/demand-intelligence/
kubectl apply -f infrastructure/kubernetes/platform/
```

### Pod Readiness Status
```text
NAME                                    READY   STATUS    RESTARTS   AGE
demand-intelligence-64d9ffcb6b-8c27g    1/1     Running   0          17s
demo-api-7d94bc9cb8-pr8xw               1/1     Running   0          18s
demo-api-7d94bc9cb8-rlq5b               1/1     Running   0          18s
grafana-748bfc6958-4s64g                1/1     Running   0          18s
platform-5fcb96db7-nfpql                1/1     Running   0          17s
prometheus-59f88487fc-n7dfv             1/1     Running   0          18s
traffic-intelligence-79bd5df9db-vn2wq   1/1     Running   0          17s
```

---

## 6. Service Discovery & Networking Validation

Cross-service communication was validated from inside the `platform` pod using internal Kubernetes DNS (`*.sentinelscale.svc.cluster.local`):

| Source | Target Service | URL | Result |
| :--- | :--- | :--- | :--- |
| `platform` | `traffic-intelligence` | `http://traffic-intelligence.sentinelscale.svc.cluster.local:8001/ready` | **HTTP 200 OK** (`status: ready`) |
| `platform` | `demand-intelligence` | `http://demand-intelligence.sentinelscale.svc.cluster.local:8002/ready` | **HTTP 200 OK** (`status: ready`) |
| `platform` | `prometheus` | `http://prometheus.sentinelscale.svc.cluster.local:9090/-/healthy` | **HTTP 200 OK** (`Prometheus Server is Healthy`) |
| `platform` | `demo-api` | `http://demo-api.sentinelscale.svc.cluster.local:8000/health` | **HTTP 200 OK** (`status: ok`) |
| Client | `demo-api` | `http://127.0.0.1:8000/products` (via port-forward) | **HTTP 200 OK** (5 products returned) |

---

## 7. RBAC Read-Only Safety Validation

The Platform service operates under a dedicated ServiceAccount (`sentinelscale-platform`) bound to Role `sentinelscale-platform-reader`:

```text
kubectl auth can-i get deployments  --as=system:serviceaccount:sentinelscale:sentinelscale-platform  -> YES
kubectl auth can-i list pods        --as=system:serviceaccount:sentinelscale:sentinelscale-platform  -> YES
kubectl auth can-i create deployments --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> NO
kubectl auth can-i update deployments --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> NO
kubectl auth can-i patch deployments  --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> NO
kubectl auth can-i delete pods        --as=system:serviceaccount:sentinelscale:sentinelscale-platform -> NO
```

---

## 8. Prometheus & Grafana Telemetry Validation

- **Prometheus Scrape Targets**: Both `demo-api.sentinelscale.svc.cluster.local:8000` and `platform.sentinelscale.svc.cluster.local:8003` report `Health: up`.
- **Grafana Datasource**: Automatically provisioned proxy datasource pointing to `http://prometheus.sentinelscale.svc.cluster.local:9090` (`status: ok`).
- **Grafana Dashboard**: `SentinelScale — Infrastructure Observability` provisioned into folder `SentinelScale`.

---

## 9. k6 Load Testing Against Kubernetes Demo API

Load tests were executed against the Kubernetes `demo-api` Service using the reusable M3-4 k6 container harness:

### 9.1 Smoke Profile (`PROFILE=smoke`, 10s nominal)
```text
k6 run /scripts/workload.js (PROFILE=smoke)
- Duration: 10.1s, Peak VUs: 2
- Total Requests: 52 (5.17 req/s)
- Checks: 100.00% passed (104 passed, 0 failed)
- http_req_duration: avg=6.04ms, p(95)=8.44ms
- http_req_failed: 0.00%
```

### 9.2 Baseline Profile (`PROFILE=baseline`, 50s nominal)
```text
k6 run /scripts/workload.js (PROFILE=baseline)
- Duration: 50.1s, Peak VUs: 10
- Total Requests: 1,424 (28.40 req/s)
- Checks: 100.00% passed (2,848 passed, 0 failed)
- http_req_duration: avg=5.65ms, med=5.34ms, p(95)=7.40ms
- http_req_failed: 0.00%
```

---

## 10. Controlled Pod Restart & Recovery Validation

A controlled resilience test was executed by terminating the `traffic-intelligence` pod:

1. **Pod Deletion**: `kubectl delete pod -l app.kubernetes.io/name=traffic-intelligence -n sentinelscale` (pod `...-vn2wq` deleted).
2. **Kubernetes Replacement**: Kubernetes immediately created replacement pod `traffic-intelligence-79bd5df9db-7rlt8` on IP `10.1.0.30`.
3. **Readiness Recovery**: The replacement pod passed probes and reached `1/1 Ready` status within 10 seconds.
4. **DNS Continuity**: `http://traffic-intelligence.sentinelscale.svc.cluster.local:8001` resolved seamlessly without client restart.
5. **Decision Orchestration**: `POST /api/v1/decision/orchestrate` successfully queried the recovered M1 pod and completed evaluation with `HTTP 200 OK` (`action: HOLD`).

---

## 11. Safety Invariants & Boundary Rules

- `dry_run = True`
- `shadow_mode = True`
- `SENTINEL_AUTONOMOUS_ACTIONS_ENABLED = False`
- **Zero Kubernetes Scaling Mutations**: No replicas mutated, no HPA resources created.
- **Frozen Contracts**: All 5 v1.0.0 JSON Schemas in `contracts/` remain strictly unchanged.

---

## 12. Automated Test Results

```text
======================================================================
 TEST EXECUTION SUMMARY
======================================================================
 - Demo API                            : PASSED (9 passed)
 - Traffic Intelligence                : PASSED (5 passed)
 - Demand Intelligence                 : PASSED (100 passed)
 - Platform & Decision Engine          : PASSED (260 passed, 2 skipped)
======================================================================
 ALL 4 SERVICE TEST SUITES PASSED SUCCESSFULLY (374 passed, 2 skipped)
======================================================================
```

---

## 13. Scope & Boundaries for Next Stages

- **Stage M3-5 establishes the live Kubernetes runtime only.**
- **Stage M3-6** will implement Kubernetes Resource Intelligence.
- **Stage M3-7** will implement real HPA comparison.
- **Stage M3-8** will execute HPA vs. SentinelScale comparative experiments.
