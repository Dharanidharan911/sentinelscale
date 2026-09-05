# Architectural Decisions — SentinelScale

> Last updated: 2026-09-05
> Original ADRs: `docs/decisions/`

---

## ADR-001: Three Independent Intelligence Module Architecture

**Status**: Accepted

**Decision**: Decompose cloud resource intelligence into three independently deployable, contract-driven microservice modules:
1. Module 1 — Traffic Intelligence
2. Module 2 — Demand Intelligence
3. Module 3 — Platform & Decision Engine

**Reason**: Traditional HPA reacts naively to aggregate metrics. Decomposing into independent modules allows clean ownership boundaries, independent deployment, and isolated testing.

---

## ADR-002: Decoupled Demand Intelligence and Non-LLM Decision Guardrails

**Status**: Accepted

**Decision (part 1)**: Demand Intelligence operates asynchronously and independently from Traffic Intelligence — it does NOT make synchronous HTTP calls to Module 1 at runtime.

**Reason**: Synchronous coupling introduces cascading latency, tight temporal dependencies, and single points of failure. Historical legitimate telemetry provided via the platform accumulator is sufficient for time-series forecasting.

**Decision (part 2)**: The Decision Engine and Policy Guardrails are strictly deterministic mathematical rules — no LLMs, no random sampling, no non-deterministic agents in the actuation path.

**Reason**: Infrastructure decisions must be provable, auditable, and bounded.

---

## ADR-003: Shadow Mode First and Baseline HPA Comparison

**Status**: Accepted

**Decision**: All scaling recommendations run in shadow mode (`dry_run=True`, `shadow_mode=True`) during all evaluation phases. No autonomous cluster mutations.

**Reason**: Deploying autonomous infrastructure controllers requires continuous empirical validation against established baselines before granting write access.

---

## ADR-004: Pluggable Telemetry Provider with No Silent Zero Fallbacks

**Status**: Accepted

**Decision**: The Resource Observer delegates metric collection to a pluggable `ResourceTelemetryProvider` ABC. All providers must raise `TelemetryProviderError` on genuine failures — never silently return zero values for unavailable metrics.

---

## ADR-005: Kubernetes Quantity Parser with Strict Validation

**Status**: Accepted

**Decision**: All Kubernetes resource quantity strings (CPU: `100m`, `2`, `0.5`; Memory: `256Mi`, `4Gi`, `500M`) must be parsed by a dedicated `quantity_parser.py` module that strictly validates and rejects unsupported/malformed quantities.

---

## ADR-006: Each Service Has Its Own Isolated PYTHONPATH

**Status**: Accepted

**Decision**: Each microservice (`demo-api/`, `services/traffic-intelligence/`, etc.) is treated as an independent Python package root. Tests run via `run_tests.py` with `PYTHONPATH` set to the service root only.

---

## ADR-007: Historical Demand Observation Accumulator & Gating (Stage F2/F3)

**Status**: Accepted

**Decision**: The Platform maintains an internal SQLite store (`demand_observations`) that ingests `TrafficAssessment` records from Module 1, strictly filters out hostile/malicious traffic (`risk_score > 0.80` or `classification == 'malicious'`), and dispatches verified legitimate demand series (`DemandObservation[]`) to Module 2.

**Reason**: Guarantees that attack traffic never enters historical demand storage or poisons future workload forecasts, while preserving Module 2's decoupling from real-time ingress.

---

## ADR-008: Formal HPA vs. SentinelScale Comparative Evaluation Layer

**Status**: Accepted

**Decision**: Implement a deterministic `HPAEvaluationService` that quantitatively compares the traditional reactive HPA baseline against SentinelScale's policy-guarded recommendation for every decision context, calculating replica deltas, pod-hours saved, and categorization.
