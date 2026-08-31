# SentinelScale

> **Security-Aware Resource Intelligence for Cloud APIs**

[![SentinelScale CI](https://github.com/sentinelscale/sentinelscale/actions/workflows/ci.yml/badge.svg)](https://github.com/sentinelscale/sentinelscale/actions)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

SentinelScale is an industry-oriented cloud resource intelligence platform that bridges API traffic security, time-series workload forecasting, and infrastructure scaling decisions.

Traditional autoscaling reacts blindly to total aggregate CPU or request volume, dangerously scaling out during DDoS attacks or bot bursts. SentinelScale assesses traffic security, estimates legitimate demand, computes traditional baseline HPA divergence, and executes deterministic policy guardrails to protect cloud infrastructure from Economic Denial of Sustainability (EDoS).

---

## Architecture at a Glance

SentinelScale is built on three decoupled, contract-driven microservice modules:

```
                    API TRAFFIC
                         │
                         ▼
                    API GATEWAY
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   Traffic Telemetry  App Metrics   Resource Telemetry
        │                                 │
        ▼                                 ▼
┌──────────────────┐             ┌──────────────────┐
│ MODULE 1         │             │ MODULE 3         │
│ Traffic          │             │ Resource State   │
│ Intelligence     │             │ Observer         │
└───────┬──────────┘             └────────┬─────────┘
        │                                 │
        ▼                                 │
   Traffic Risk &                         │
   Classification                         │
        │                                 │
        └────────────────┐                │
                         ▼                │
                ┌──────────────────┐      │
                │ MODULE 2         │      │
                │ Demand           │      │
                │ Intelligence     │      │
                └────────┬─────────┘      │
                         │                │
                         ▼                │
                Predicted Legitimate      │
                Workload Demand           │
                         │                │
                         └────────┬───────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ MODULE 3         │
                         │ Decision Engine  │
                         │ & Baseline HPA   │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ POLICY GUARDRAIL │
                         │ (Deterministic)  │
                         └────────┬─────────┘
                                  │
                   ┌──────────────┼──────────────┐
                   ▼              ▼              ▼
                 SCALE        RATE_LIMIT        HOLD
              (Legitimate)    (Suspicious)   (Mitigation)
```

---

## Key Modules & Boundaries

1. **Module 1: Traffic Intelligence (`services/traffic-intelligence`)**
   - Ingests API traffic telemetry, extracts behavioral features, and scores security risk and legitimacy.
   - Public Contract: [`contracts/traffic/traffic_assessment.schema.json`](file:///c:/SentinelScale/contracts/traffic/traffic_assessment.schema.json)
2. **Module 2: Demand Intelligence (`services/demand-intelligence`)**
   - Independent time-series forecaster predicting future legitimate application demand without synchronous dependency on Traffic Intelligence.
   - Public Contract: [`contracts/demand/demand_forecast.schema.json`](file:///c:/SentinelScale/contracts/demand/demand_forecast.schema.json)
3. **Module 3: Platform, Resource Observer & Decision Engine (`services/platform`)**
   - Tracks Kubernetes cluster state, computes traditional reactive HPA baseline comparisons, aggregates `DecisionContext`, and executes deterministic policy guardrails in dry-run/shadow mode.
   - Public Contracts: [`contracts/resources/resource_state.schema.json`](file:///c:/SentinelScale/contracts/resources/resource_state.schema.json) and [`contracts/decisions/scaling_decision.schema.json`](file:///c:/SentinelScale/contracts/decisions/scaling_decision.schema.json)
4. **Demo Workload API (`demo-api`)**
   - Realistic e-commerce cloud application used to generate authentic traffic patterns and telemetry.

---

## Quickstart

### Start the Local Stack with Docker Compose

```bash
cp .env.example .env
docker-compose up --build
```

### Endpoints
- **Demo API**: `http://localhost:8000/docs`
- **Traffic Intelligence**: `http://localhost:8001/docs`
- **Demand Intelligence**: `http://localhost:8002/docs`
- **Platform & Decision Engine**: `http://localhost:8003/docs`
- **Prometheus**: `http://localhost:9090`

### Run Test Suite

```bash
# Run all services in isolated test environments
python run_tests.py
```

---

## Documentation

- [Architecture Design & Data Flow](file:///c:/SentinelScale/ARCHITECTURE.md)
- [API Contracts & JSON Schemas](file:///c:/SentinelScale/CONTRACTS.md)
- [Developer Onboarding & Git Workflow](file:///c:/SentinelScale/DEVELOPMENT.md)
- [Architectural Decision Records (ADRs)](file:///c:/SentinelScale/docs/decisions/)
