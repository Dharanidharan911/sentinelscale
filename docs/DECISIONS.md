# Architectural Decisions — SentinelScale

> Last updated: 2026-09-01
> Original ADRs: `docs/decisions/`

---

## ADR-001: Three Independent Intelligence Module Architecture

**Status**: Accepted

**Decision**: Decompose cloud resource intelligence into three independently deployable, contract-driven microservice modules:
1. Module 1 — Traffic Intelligence
2. Module 2 — Demand Intelligence
3. Module 3 — Platform & Decision Engine

**Reason**: ADR-001 documents this directly — traditional HPA reacts naively to aggregate metrics. Decomposing into independent modules allows clean ownership boundaries, independent deployment, and independent testability.

**Alternatives considered**: Monolithic platform with integrated ML pipeline (not chosen — creates coupling and shared state).

**Consequences**:
- Each module has its own `app/` package, `requirements.txt`, `Dockerfile`, `PYTHONPATH`
- Communication is strictly via versioned JSON Schema contracts
- No Python-level imports across service boundaries at runtime
- Three developer branches: `member1/`, `member2/`, `member3/`

---

## ADR-002: Decoupled Demand Intelligence and Non-LLM Decision Guardrails

**Status**: Accepted

**Decision (part 1)**: Demand Intelligence operates asynchronously and independently from Traffic Intelligence — it does NOT make synchronous HTTP calls to Module 1 at runtime.

**Reason (from ADR-002)**: Synchronous coupling introduces cascading latency, tight temporal dependencies, and single points of failure. Historical telemetry is sufficient for time-series forecasting without real-time security context.

**Decision (part 2)**: The Decision Engine and Policy Guardrails are strictly deterministic mathematical rules — no LLM, no random sampling, no non-deterministic agents.

**Reason (from ADR-002)**: Infrastructure decisions must be provable, auditable, and bounded. LLMs can hallucinate actions, have unbounded latency, and are unprovable.

**Alternatives considered**: Synchronous pipeline (M1 → M2 → M3) — not chosen. LLM-based decision agent — explicitly rejected.

**Consequences**:
- Module 2 must maintain its own telemetry ingestion path (currently mocked, future: direct Prometheus access)
- Decision logic lives in `decision_engine.py` as pure Python with no ML runtime dependencies
- `dry_run=True` is hardcoded in `DecisionEngine.evaluate_decision()` as a code-level safety guarantee

---

## ADR-003: Shadow Mode First and Baseline HPA Comparison

**Status**: Accepted

**Decision**: All scaling recommendations run in shadow mode (`dry_run=True`, `shadow_mode=True`) during the entire bootstrap and evaluation phase. No real Kubernetes mutations.

**Reason (from ADR-003)**: Deploying autonomous infrastructure controllers into production requires continuous empirical validation against established baselines before granting write access. Shadow mode provides zero-risk evidence collection.

**Consequences**:
- `SENTINEL_AUTONOMOUS_ACTIONS_ENABLED=false` in all environments
- Every `ScalingDecision` contains `baseline_hpa_recommended_pods` and `pod_delta_vs_baseline` for comparison
- `experiments/` directory contains shadow-mode evaluation scenario files
- Platform RBAC (`infrastructure/kubernetes/platform/rbac.yaml`) grants read-only access only

---

## ADR-004: Pluggable Telemetry Provider with No Silent Zero Fallbacks

**Status**: Accepted (inferred from Phase 1A/1B/2A implementation)

**Decision**: The Resource Observer delegates metric collection to a pluggable `ResourceTelemetryProvider` ABC. All providers must raise `TelemetryProviderError` on genuine failures — never silently return zero values for unavailable metrics.

**Reason**: Silently returning zero for unavailable infrastructure metrics (e.g., "CPU utilization = 0.0" when Prometheus is down) would corrupt the Decision Engine's logic and produce wrong scaling decisions. Explicit failure is safer than silent fake data.

**Alternatives considered**: Fallback chain returning zeros on missing metrics — explicitly rejected during Phase 1B user review.

**Consequences**:
- `TelemetryProviderError` is a first-class exception type in `base.py`
- HTTP 502 Bad Gateway is returned when a provider fails (not 200 with zero data)
- Provider selection via `TELEMETRY_PROVIDER` env var: `mock` (default) | `prometheus` | `kubernetes`
- Mock is always preserved as fallback for CI/CD (no real cluster needed)

---

## ADR-005: Kubernetes Quantity Parser with Strict Validation

**Status**: Accepted (inferred from Phase 2A implementation)

**Decision**: All Kubernetes resource quantity strings (CPU: `100m`, `2`, `0.5`; Memory: `256Mi`, `4Gi`, `500M`) must be parsed by a dedicated `quantity_parser.py` module that strictly validates and rejects unsupported/malformed quantities.

**Reason**: Silently interpreting an unknown suffix (e.g., `256X`) as raw bytes would produce wildly incorrect resource aggregations. The user mandate during Phase 2A explicitly required no silent interpretations.

**Alternatives considered**: Approximate regex-based parser — explicitly rejected.

**Consequences**:
- `parse_cpu_quantity()` and `parse_memory_quantity()` raise `TelemetryProviderError` on unknown/malformed input
- Supported: millicores `m`, plain/decimal cores, binary SI (`Ki`/`Mi`/`Gi`/`Ti`/`Pi`/`Ei`), decimal SI (`k`/`K`/`M`/`G`/`T`/`P`/`E`), plain integer bytes
- Tests in `test_kubernetes_provider.py` cover both valid and invalid formats

---

## ADR-006: Each Service Has Its Own Isolated PYTHONPATH

**Status**: Accepted (inferred from test infrastructure)

**Decision**: Each microservice (`demo-api/`, `services/traffic-intelligence/`, etc.) is treated as an independent Python package root. Tests run with `PYTHONPATH` set to the service root only.

**Reason**: Multiple services have a top-level `app/` package. Without isolation, Python would import `app` from the wrong service, causing cross-contamination.

**Alternatives considered**: Namespace packages, renaming packages (e.g., `platform_app`) — not chosen, would require modifying all existing imports.

**Consequences**:
- `run_tests.py` launches each service's tests in a subprocess with isolated `PYTHONPATH`
- No root-level `conftest.py` hacking `sys.path`
- Cannot import across service boundaries at Python level

---

## ADR-007: No Heavy Distributed Middleware in Bootstrap

**Status**: Accepted (from ADR-002)

**Decision**: Kafka, Redis, Airflow, Spark, and similar distributed middleware are excluded from the bootstrap phase.

**Reason**: Keeping the local developer stack lightweight (just `docker-compose up`) accelerates iteration, reduces onboarding time, and avoids premature infrastructure complexity.

**Consequences**:
- No event streaming between services — pull-based HTTP calls only
- All state is ephemeral — no persistence layer
- Module 2 does not consume a Kafka topic for real telemetry yet

---

## Open Questions (Not Yet Decided)

1. **How will Module 2 (Demand Intelligence) actually consume historical telemetry for real forecasting?** Options: direct Prometheus query, Kafka topic, periodic batch job. Not yet decided.
2. **Which ML framework will Module 1 use for real traffic classification?** Options: XGBoost, Isolation Forest, Prophet. Mentioned in `ARCHITECTURE.md` but not implemented.
3. **When will `autonomous_actions_enabled` be unlocked?** Requires shadow-mode validation results showing consistent accuracy vs. HPA baseline. Criteria not yet defined.
4. **Will Phase 2B use a new provider class or extend existing ones?** See `docs/MODULE_2B.md`.
