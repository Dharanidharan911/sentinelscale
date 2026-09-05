# SentinelScale

> **Security-Aware Cloud Resource Intelligence Platform**

[![SentinelScale CI](https://github.com/sentinelscale/sentinelscale/actions/workflows/ci.yml/badge.svg)](https://github.com/sentinelscale/sentinelscale/actions)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-e92063.svg)](https://docs.pydantic.dev/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

SentinelScale is a security-aware cloud resource intelligence platform that solves the problem of **Economic Denial of Sustainability (EDoS)** in modern cloud architectures.

Traditional Kubernetes Horizontal Pod Autoscalers (HPA) react blindly to raw infrastructure metrics (CPU utilization, memory usage, or aggregate request volume). When an application experiences malicious traffic surges (Layer 7 DDoS floods, credential stuffing, scraping swarms, or bot bursts), traditional HPA scales out blindly — spinning up redundant, expensive pod replicas to service attack traffic, wasting infrastructure budgets, and cascading pressure to downstream backends.

SentinelScale distinguishes **legitimate business demand** from **malicious traffic surges**, extracts true business workload requirements, and drives infrastructure capacity decisions based only on genuine demand — while suppressing wasteful scale-out during attacks.

---

## Architecture at a Glance

SentinelScale is organized into three contract-driven, independently deployable microservices plus a realistic demo workload and comparative evaluation layer:

```
[ Incoming API Traffic ]
           │
           ▼
   [ Demo API :8000 ] ──► [ Telemetry Collector ]
                                 │ (TrafficTelemetryInput)
                                 ▼
                     [ Module 1: Traffic Intelligence :8001 ]
                                 │ (TrafficAssessment: risk, classification, legitimate_rps)
                                 ▼
                     [ F2 Demand Observation Accumulator (SQLite) ]
                                 │ (Security Gating: Risk <= 0.80, classification != malicious)
                                 ▼
                     [ Module 2: Demand Intelligence :8002 ]
                                 │ (DemandForecast: predicted_legitimate_rps, confidence)
                                 ▼
                     [ Module 3: Platform & Decision Engine :8003 ]
                        ├── Resource Observer (ResourceState)
                        ├── Baseline Reactive HPA Calculator
                        ├── SentinelScale Decision Engine (Deterministic)
                        ├── Policy Guardrails (Bounds & Surge Protection)
                        └── HPA vs. SentinelScale Evaluator
                                 │
                                 ▼
                     [ ScalingDecision + EvaluationResult ]
                     (dry_run=true, shadow_mode=true)
```

---

## Core Modules & Responsibilities

| Module | Service Directory | Port | Responsibility | Public Contract |
| :--- | :--- | :---: | :--- | :--- |
| **Demo API** | `demo-api/` | `8000` | Realistic e-commerce target cloud application generating authentic business traffic and metrics. | `/api/v1/products`, `/users`, `/metrics` |
| **Module 1: Traffic Intelligence** | `services/traffic-intelligence/` | `8001` | Analyzes request telemetry, IP concentrations, User-Agent distributions, and error rates to assess security risk and estimate legitimate vs. suspicious RPS. | [`contracts/traffic/traffic_assessment.schema.json`](contracts/traffic/traffic_assessment.schema.json) |
| **Module 2: Demand Intelligence** | `services/demand-intelligence/` | `8002` | Executes deterministic time-series forecasting (recency-weighted moving average and linear trend projection) over historical legitimate observations. | [`contracts/demand/demand_forecast.schema.json`](contracts/demand/demand_forecast.schema.json) |
| **Module 3: Platform & Decision Engine** | `services/platform/` | `8003` | Collects resource state, aggregates decision context, computes reactive HPA baseline comparison, enforces policy guardrails, and derives comparative business impact. | [`contracts/resources/resource_state.schema.json`](contracts/resources/resource_state.schema.json)<br>[`contracts/decisions/scaling_decision.schema.json`](contracts/decisions/scaling_decision.schema.json) |

---

## How Legitimate Demand is Separated from Suspicious Traffic

1. **Empirical Telemetry Extraction**: Ingress request events are measured across time windows to determine total RPS, top-IP concentration ratios, non-standard User-Agent proportions, single-endpoint focus, and status code distributions.
2. **Security Risk Classification**: Module 1 evaluates telemetry against behavioral rules (`traffic-rules-v1`), categorizing traffic as `legitimate`, `suspicious`, or `malicious`, and deriving an explicit `legitimate_rps_estimate`.
3. **Historical Demand Accumulation & Gating**: The Platform's Stage F2 accumulator persists legitimate demand observations to SQLite (`data/sentinelscale_history.db`). Observations with high risk (`risk_score > 0.80`), low legitimacy, low confidence, or `malicious` classification are **strictly rejected**.
4. **Demand Forecasting**: Module 2 receives only authenticated, gated historical demand observations (`DemandObservation[]`), ensuring that **attack traffic never poisons the forecasting model**.
5. **Policy-Guarded Decisions**: Module 3's Decision Engine recommends replicas to satisfy predicted legitimate demand. During attacks where legitimate demand is within current capacity, SentinelScale issues `action = HOLD`, suppressing wasteful scale-out.

---

## Safety Model & Invariants

SentinelScale operates under strict, code-enforced safety guarantees:

- **`SENTINEL_DRY_RUN = True`**: All scaling recommendations are advisory; no autonomous infrastructure mutations are performed.
- **`SENTINEL_SHADOW_MODE = True`**: Recommendations are evaluated in parallel against traditional reactive HPA baselines.
- **`SENTINEL_AUTONOMOUS_ACTIONS_ENABLED = False`**: Actuation write permissions to Kubernetes or cloud providers are disabled.
- **Deterministic Decision Logic**: The Decision Engine and Policy Guardrails use pure mathematical and rule-based logic — **no LLMs or non-deterministic algorithms in the scaling actuation path**.
- **0 Kubernetes Mutations**: During all validation phases, zero cluster mutations or `kubectl` modification commands were executed.

---

## Quickstart & Local Execution

### 1. Environment Setup

```bash
# Clone repository and create Python virtual environment (Python 3.12+)
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# or: .venv\Scripts\activate  # Windows

# Install service dependencies
pip install -r demo-api/requirements.txt
pip install -r services/traffic-intelligence/requirements.txt
pip install -r services/demand-intelligence/requirements.txt
pip install -r services/platform/requirements.txt
```

### 2. Start the Microservices

You can start the full stack via Docker Compose or as independent local processes:

#### Option A: Docker Compose
```bash
docker-compose up --build
```

#### Option B: Independent Processes (Local Development)
```bash
# Terminal 1: Demo API
cd demo-api && python -m uvicorn app.main:app --port 8000 --host 127.0.0.1

# Terminal 2: Traffic Intelligence
cd services/traffic-intelligence && python -m uvicorn app.main:app --port 8001 --host 127.0.0.1

# Terminal 3: Demand Intelligence
cd services/demand-intelligence && python -m uvicorn app.main:app --port 8002 --host 127.0.0.1

# Terminal 4: Platform & Decision Engine
cd services/platform && python -m uvicorn app.main:app --port 8003 --host 127.0.0.1
```

### 3. Service Endpoints

- **Demo API**: `http://localhost:8000/docs` (Health: `GET /health`, Metrics: `GET /metrics`)
- **Traffic Intelligence**: `http://localhost:8001/docs` (Assess: `POST /api/v1/traffic/assess`)
- **Demand Intelligence**: `http://localhost:8002/docs` (Forecast: `POST /api/v1/demand/forecast`)
- **Platform & Decision Engine**: `http://localhost:8003/docs` (Decide: `POST /api/v1/decision/evaluate`, Evaluate: `POST /api/v1/evaluation/evaluate`)

---

## Testing & Validation

### Canonical Full-Suite Test Command

Run the official isolated test runner from the repository root:

```bash
python run_tests.py
```

> [!IMPORTANT]
> Because SentinelScale is a multi-service monorepo where each microservice defines its own independent `app/` and `tests/` packages, running bare `pytest -q` from the root causes namespace collisions. `python run_tests.py` executes each service in an isolated subprocess with its dedicated `PYTHONPATH`.

### Running Individual Service Test Suites

```powershell
# Windows PowerShell:
$env:PYTHONPATH="$PWD\demo-api"; python -m pytest demo-api/tests -v
$env:PYTHONPATH="$PWD\services\traffic-intelligence"; python -m pytest services/traffic-intelligence/tests -v
$env:PYTHONPATH="$PWD\services\demand-intelligence"; python -m pytest services/demand-intelligence/tests -v
$env:PYTHONPATH="$PWD\services\platform"; python -m pytest services/platform/tests -v

# Linux / macOS Bash:
PYTHONPATH="$PWD/demo-api" python -m pytest demo-api/tests -v
PYTHONPATH="$PWD/services/traffic-intelligence" python -m pytest services/traffic-intelligence/tests -v
PYTHONPATH="$PWD/services/demand-intelligence" python -m pytest services/demand-intelligence/tests -v
PYTHONPATH="$PWD/services/platform" python -m pytest services/platform/tests -v
```

### Current Test Baseline (Verified Passing)
- **Demo API**: 9 passed
- **Traffic Intelligence**: 5 passed
- **Demand Intelligence**: 100 passed
- **Platform & Decision Engine**: 243 passed, 1 skipped
- **Total**: **357 passed, 1 skipped, 0 failed**

---

## Live Multi-Process Validation (Stage F6)

To execute real dynamic HTTP traffic workloads against the running microservices:

```bash
python scripts/validate_stage_f6_live.py
```

### Validated Scenarios Summary

| Scenario | Workload Profile | M1 Assessment | F2 Gating | M2 Forecast | SentinelScale Decision | HPA Baseline | Evaluated Difference |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **A: Steady Legitimate** | 50 RPS, distributed IPs, normal UA | Risk 0.05 (`legitimate`) | **Accepted** | 54.9 RPS | `SCALE` (2 pods) | 4 pods | Delta: -2 replicas (2.0 pod-hrs/hr saved) |
| **B: Flash Crowd** | 250 RPS, distributed IPs, normal UA | Risk 0.16 (`legitimate`) | **Accepted** | 70.9 RPS | `SCALE` (2 pods) | 4 pods | Delta: -2 replicas |
| **C: Hostile L7 Flood** | 300 RPS, 92% IP conc, 100% bot UA | Risk 1.00 (`malicious`) | **REJECTED** | 70.9 RPS (unpoisoned) | `HOLD` (2 pods) | 4 pods | **Attack scale-up suppressed** |
| **D: Mixed Traffic** | 80 RPS, 36% IP conc, 36% bot UA | Risk 0.41 (`legitimate`) | **Accepted** | 47.5 RPS | `SCALE` (2 pods) | 4 pods | Delta: -2 replicas |

---

## Known Limitations

1. **Local Telemetry Provider**: In local standalone validation where an external Kubernetes cluster and Prometheus server are not attached, Platform operates with its built-in high-fidelity `MockTelemetryProvider`.
2. **Short Burst Durations**: Rapid 1.0s scenario execution generates composite confidence scores around ~0.395, which deterministically flags comparative evaluation as `UNCERTAIN` to prevent uncalibrated policy enforcement (full 60s+ production windows yield confidence >0.70).
3. **Dry-Run Enforcement**: In accordance with project safety constraints, all decisions are strictly shadow/dry-run recommendations; automated cluster mutation remains disabled.

---

## Project Documentation Index

| Document | Description |
| :--- | :--- |
| [`AGENTS.md`](AGENTS.md) | Master instructions for AI agents and developers |
| [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md) | High-level problem statement, requirements, and system state |
| [`docs/PROGRESS.md`](docs/PROGRESS.md) | Phase-by-phase implementation progress and verified test baseline |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture, components, and module boundaries |
| [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md) | End-to-end data flow and stage-by-stage transformations |
| [`docs/API_CONTRACTS.md`](docs/API_CONTRACTS.md) | Frozen JSON Schema contracts, models, and endpoints |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Architectural Decision Records (ADRs) |
| [`docs/STAGE_F6_LIVE_VALIDATION.md`](docs/STAGE_F6_LIVE_VALIDATION.md) | Full Stage F6 live multi-process validation report |
| [`docs/HPA_VS_SENTINELSCALE_EVALUATION.md`](docs/HPA_VS_SENTINELSCALE_EVALUATION.md) | Comparative evaluation layer design and metrics |

---

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.
