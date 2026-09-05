# Project Context — SentinelScale

> Last updated: 2026-09-01

---

## Problem Statement

Traditional cloud autoscalers (Kubernetes HPA) react blindly to aggregate infrastructure metrics — CPU utilization, memory pressure, or total request volume. During adversarial traffic events (Layer 7 DDoS floods, credential stuffing, web scraping swarms, bot bursts), standard HPA:

- **Scales out blindly** — spinning up 10–50 expensive pod replicas to service illegitimate traffic
- **Wastes money** (Economic Denial of Sustainability / EDoS)
- **Destabilizes backends** — cascade failures hit databases and third-party APIs
- **Has no intent awareness** — infrastructure layers are completely isolated from edge security signals

---

## Project Objective

SentinelScale bridges three domains that have historically operated in isolation:

1. **API Traffic Security** — distinguish legitimate users from attackers
2. **Time-Series Demand Forecasting** — predict true business workload
3. **Cloud Infrastructure Scaling Decisions** — act only on legitimate demand

The result: a security-aware autoscaler that **holds replicas steady** during attacks while **scaling correctly** for real demand spikes.

---

## Target Users / Use Case

- **Platform engineers** at companies running public-facing cloud APIs that face volumetric traffic attacks
- **FinTech, e-commerce, SaaS platforms** where attack-induced overprovisioning has direct financial consequences
- **DevOps/MLOps teams** evaluating autonomous infrastructure controllers before granting real write access

Primary use case: An e-commerce API is hit with a 2,500 RPS bot flood. Only 850 RPS is legitimate. Standard HPA would scale from 4 → 12 pods. SentinelScale holds at 4 pods, saves ~8 pod-hours of cost, and triggers gateway rate limiting for the suspicious traffic.

---

## Core Functionality

1. **Traffic Assessment** — evaluates incoming traffic telemetry, scores security risk $[0.0, 1.0]$, classifies as `legitimate` / `suspicious` / `malicious`
2. **Demand Forecasting** — independently forecasts legitimate workload RPS over configurable horizons with confidence intervals
3. **Resource Observation** — queries real infrastructure state (pod counts, CPU/memory utilization, request rates) from Prometheus or the Kubernetes API
4. **Decision Engine** — aggregates all three signals, computes security-aware pod recommendations, compares against standard HPA baseline
5. **Policy Guardrails** — deterministic, non-LLM safety boundaries: min/max pod clamping, step-up surge protection, dry-run enforcement
6. **Shadow-Mode Evaluation** — all recommendations run in shadow mode alongside live cluster operations — no real mutations yet

---

## Major Modules

| Module | Service | Purpose |
| :--- | :--- | :--- |
| **Module 1: Traffic Intelligence** | `services/traffic-intelligence/` | Assess traffic telemetry for risk, legitimacy, and classification |
| **Module 2: Demand Intelligence** | `services/demand-intelligence/` | Forecast legitimate future demand independently |
| **Module 3: Platform & Decision Engine** | `services/platform/` | Observe resources, compute decisions, enforce guardrails |
| **Demo API** | `demo-api/` | Realistic target workload generating business telemetry |

---

## Technology Stack

| Layer | Technology |
| :--- | :--- |
| API framework | FastAPI (async) |
| Data validation | Pydantic v2 |
| Configuration | pydantic-settings (.env) |
| HTTP client | httpx (async) |
| Metrics | Prometheus (via `/metrics` endpoint on demo-api) |
| Containerization | Docker + Docker Compose |
| Orchestration | Kubernetes (manifests in `infrastructure/kubernetes/`) |
| Testing | pytest + pytest-asyncio |
| Python version | 3.12+ |
| Schema validation | jsonschema |

**Intentionally excluded from bootstrap:** Kafka, Redis, Airflow, Spark, any LLM/generative AI in the actuation path.

---

## Current System State

**Phase 0 (Bootstrap)**: ✅ Complete
- All 4 service test suites pass in isolation (63 tests total)
- All JSON Schema contracts are frozen and enforced
- Docker Compose full-stack runs

**Phase 1A (Telemetry Provider Abstraction)**: ✅ Complete
- `ResourceTelemetryProvider` ABC + `MockTelemetryProvider` implemented
- Factory pattern with `TELEMETRY_PROVIDER` env var selection

**Phase 1B (Prometheus Telemetry)**: ✅ Complete
- `PrometheusTelemetryProvider` implemented
- Queries normalized CPU utilization, memory utilization, request rate, P95 latency, error rate

**Phase 2A (Kubernetes Resource Telemetry)**: ✅ Complete
- `KubernetesTelemetryProvider` implemented
- Queries Kubernetes REST API for real pod counts, container resource specs
- `quantity_parser.py` for strict Kubernetes quantity parsing
- RBAC manifests: `infrastructure/kubernetes/platform/rbac.yaml`

**Phase 2B (Hybrid Prometheus + Kubernetes Aggregation)**: ❌ NOT IMPLEMENTED
- This is the next phase to implement

---

## Important Constraints

1. **`dry_run=True` always** — no real Kubernetes mutations until explicitly authorized
2. **`shadow_mode=True` always** — decisions are compared against HPA baseline but not applied
3. **`autonomous_actions_enabled=False` always** — currently a read-only intelligence system
4. **Contracts are frozen** — `contract_version: "1.0.0"` across all schemas
5. **No LLMs in actuation path** — all decisions are deterministic math
6. **Service isolation** — each service has its own `PYTHONPATH`; never import across service boundaries at runtime
7. **Mock is always the default provider** (`TELEMETRY_PROVIDER=mock`) — CI never requires a real cluster

---

## Overall Workflow

```
API Traffic → Gateway → demo-api
                   └→ Prometheus metrics

Prometheus → Module 1 (Traffic Intelligence)
             Module 2 (Demand Intelligence)      (independent)
             Module 3 Resource Observer (Prometheus or Kubernetes API)

Module 1 TrafficAssessment ─┐
Module 2 DemandForecast    ─┤→ DecisionContext → Decision Engine → ScalingDecision
Module 3 ResourceState     ─┘                                    (dry-run, shadow)
```

---

## Service Endpoints Summary

| Service | Port | Key Endpoints |
| :--- | :--- | :--- |
| demo-api | 8000 | `/health`, `/ready`, `/metrics`, `/products`, `/users` |
| traffic-intelligence | 8001 | `/health`, `/ready`, `POST /api/v1/traffic/assess` |
| demand-intelligence | 8002 | `/health`, `/ready`, `POST /api/v1/demand/forecast` |
| platform | 8003 | `/health`, `/ready`, `/version`, `GET /api/v1/resources/current`, `POST /api/v1/decision/evaluate` |
| prometheus | 9090 | Prometheus UI |
