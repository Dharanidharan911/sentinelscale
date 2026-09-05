# Project Context — SentinelScale

> Last updated: 2026-09-05
> Verified test baseline: `python run_tests.py` — 357 passed, 1 skipped

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

The result: a security-aware resource intelligence system that **holds replicas steady** during attacks while **scaling correctly** for real legitimate demand spikes.

---

## Target Users / Use Case

- **Platform engineers** at companies running public-facing cloud APIs that face volumetric traffic attacks
- **FinTech, e-commerce, SaaS platforms** where attack-induced overprovisioning has direct financial consequences
- **DevOps/MLOps teams** evaluating autonomous infrastructure controllers before granting real write access

Primary use case: An e-commerce API is hit with a 300 RPS bot flood. Only genuine traffic is legitimate. Standard HPA would scale out blindly based on CPU utilization. SentinelScale identifies high traffic risk, filters the attack from demand forecasting, holds at baseline capacity (e.g. 2 pods), and suppresses unnecessary scale-out.

---

## Core Functionality

1. **Traffic Assessment** — evaluates incoming traffic telemetry, scores security risk $[0.0, 1.0]$, classifies as `legitimate` / `suspicious` / `malicious`, and derives `legitimate_rps_estimate`
2. **Demand Observation Accumulation & Gating** — validates and persists historical legitimate demand into SQLite (`demand_observations`), gating out malicious and high-risk traffic
3. **Demand Forecasting** — independently forecasts legitimate workload RPS over configurable horizons using recency-weighted moving averages and linear trend projections
4. **Resource Observation** — queries real-time infrastructure state (pod counts, CPU/memory utilization, request rates) via pluggable providers (Mock, Prometheus, Kubernetes, Hybrid)
5. **Decision Engine** — aggregates all signals, computes security-aware pod recommendations, compares against standard reactive HPA baseline
6. **Policy Guardrails** — deterministic, non-LLM safety boundaries: min/max pod clamping, step-up surge protection, dry-run enforcement
7. **Shadow-Mode Evaluation** — all recommendations run in shadow mode alongside live cluster operations without performing autonomous mutations

---

## Major Modules

| Module | Service | Purpose |
| :--- | :--- | :--- |
| **Module 1: Traffic Intelligence** | `services/traffic-intelligence/` | Assess traffic telemetry for risk, legitimacy, and classification (`traffic-rules-v1`) |
| **Module 2: Demand Intelligence** | `services/demand-intelligence/` | Forecast legitimate future demand from historical observation series (`demand-v1`) |
| **Module 3: Platform & Decision Engine** | `services/platform/` | Observe resources, aggregate context, execute decision engine, enforce guardrails, and evaluate HPA divergence |
| **Demo API** | `demo-api/` | Realistic target workload generating business telemetry |

---

## Technology Stack

| Layer | Technology |
| :--- | :--- |
| API framework | FastAPI (async) / Uvicorn |
| Data validation | Pydantic v2 |
| Configuration | pydantic-settings (.env) |
| HTTP client | httpx (async) |
| Database | SQLite (WAL mode, parameterized queries) |
| Metrics | Prometheus text format (`GET /metrics`) |
| Containerization | Docker + Docker Compose |
| Orchestration | Kubernetes (manifests in `infrastructure/kubernetes/`) |
| Testing | pytest + pytest-asyncio (isolated runner `run_tests.py`) |
| Python version | 3.12+ |
| Schema validation | jsonschema |

**Intentionally excluded from actuation path:** Kafka, Redis, Airflow, Spark, any LLM/generative AI in the scaling decision path.

---

## Current System State

- **Phases 0–5C**: ✅ COMPLETE (contracts, telemetry providers, decision engine, observation scheduler, SQLite audit history, Prometheus metrics, historical intelligence, anomaly intelligence, predictive intelligence)
- **Milestone & Stage E**: ✅ COMPLETE (formal comparative HPA evaluation, cross-module integration)
- **Stages F1–F6**: ✅ COMPLETE (traffic harness, demand observation accumulator, M2 observation dispatch, E2E dynamic scenarios, comparative evaluation, live multi-process validation)
- **Test Baseline**: 357 tests passed, 1 skipped across all 4 microservice suites.

---

## Important Safety Invariants

1. **`dry_run=True` always** — no real Kubernetes mutations until explicitly authorized
2. **`shadow_mode=True` always** — decisions are compared against HPA baseline but not applied
3. **`autonomous_actions_enabled=False` always** — currently a read-only intelligence and evaluation platform
4. **Contracts are frozen** — `contract_version: "1.0.0"` across all JSON schemas
5. **No LLMs in actuation path** — all decisions are deterministic rules and mathematics
6. **Service isolation** — each service has its own `PYTHONPATH`; cross-service communication occurs via HTTP/JSON
7. **Mock is always the default provider** (`TELEMETRY_PROVIDER=mock`) — CI never requires a real cluster

---

## Overall Workflow

```
API Traffic → Gateway → demo-api
                   └→ Telemetry Collector
                             │
                      Module 1 (Traffic Intelligence)
                             │ TrafficAssessment (legitimate_rps_estimate)
                             ▼
                      F2 Demand Observation Accumulator (SQLite)
                             │ Security Gating (Risk <= 0.80)
                             ▼
                      Module 2 (Demand Intelligence)
                             │ DemandForecast
                             ▼
Module 3 Resource Observer ──┼──► DecisionContext ──► Decision Engine ──► Policy Guardrails ──► ScalingDecision
(Mock / Prom / K8s / Hybrid) │                                                                 (dry-run, shadow)
                             │
                             └────────────────────────────────────────────────────────► Evaluator ──► EvaluationResult
```

---

## Service Endpoints Summary

| Service | Port | Key Endpoints |
| :--- | :---: | :--- |
| **demo-api** | `8000` | `/health`, `/ready`, `/metrics`, `/api/v1/products`, `/users` |
| **traffic-intelligence** | `8001` | `/health`, `/ready`, `POST /api/v1/traffic/assess` |
| **demand-intelligence** | `8002` | `/health`, `/ready`, `POST /api/v1/demand/forecast` |
| **platform** | `8003` | `/health`, `/ready`, `/version`, `/metrics`, `GET /api/v1/resources/current`, `POST /api/v1/decision/evaluate`, `POST /api/v1/decision/orchestrate`, `POST /api/v1/evaluation/evaluate`, `GET /api/v1/history`, `GET /api/v1/intelligence/...` |
| **prometheus** | `9090` | Prometheus UI |
