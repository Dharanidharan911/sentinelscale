# SentinelScale — Implementation Context
> **For AI coding agents and developers starting a new conversation.**  
> This document is the project's memory outside chat history. Read it before making changes.

---

## 1. Project Overview

**SentinelScale** — Security-aware resource intelligence and autoscaling for cloud APIs.

Core principle: *Don't scale for traffic. Scale for trusted, legitimate demand.*

Architecture:
```
API Traffic → Traffic Intelligence → Demand Intelligence → Resource Intelligence
                                                              → Decision Engine
                                                              → Policy Guardrails
                                                              → ScalingDecision → Kubernetes
```

---

## 2. Module Ownership

| Module | Service | Branch | Owner | Contract Output |
|---|---|---|---|---|
| Traffic Intelligence | `services/traffic-intelligence` | `member1/traffic-intelligence` | Member 1 | `TrafficAssessment` |
| Demand Intelligence | `services/demand-intelligence` | `member2/demand-intelligence` | Member 2 | `DemandForecast` |
| Platform / Resource Intelligence | `services/platform` | `member3/platform` | Member 3 | `ResourceState`, `DecisionContext`, `ScalingDecision` |

**Module boundaries are frozen.** Do not implement Member 1 logic in Member 2. Do not implement Member 2 logic in Member 3.

---

## 3. Contract Registry

| Contract | File | Version | Status |
|---|---|---|---|
| `DemandForecast` | `contracts/demand/demand_forecast.schema.json` | `1.0.0` | **FROZEN** |
| `TrafficAssessment` | `contracts/traffic/traffic_assessment.schema.json` | `1.0.0` | **FROZEN** |
| `DecisionContext` | (in platform) | `1.0.0` | **FROZEN** |
| `ScalingDecision` | (in platform) | `1.0.0` | **FROZEN** |

**Do not modify contract files without team agreement and version bump.**

---

## 4. Member 2 — Demand Intelligence — Current Implementation State

### Status: ✅ INTEGRATION READY (Checkpoint 3)

### Completed Phases

| Phase | Description | Status |
|---|---|---|
| 0 | Contract & architecture freeze | ✅ Done |
| 1 | Provider abstraction | ✅ Done |
| 2 | DemandObservation domain model | ✅ Done |
| 3 | Historical data window via MockDemandProvider | ✅ Done |
| 4 | Forecast Quality Hardening (irregular intervals, bounds) | ✅ Done |
| 5 | Deterministic baseline forecast (RWMA + trend) | ✅ Done |
| 6 | Trend detection (linear regression slope) | ✅ Done |
| 7 | Forecasting engine separation | ✅ Done |
| 8 | Forecast horizon support | ✅ Done |
| 9 | Confidence scoring | ✅ Done |
| 10 | Forecast sanity guardrails | ✅ Done |
| 11 | DemandForecast construction | ✅ Done |
| 12 | API layer (POST /api/v1/demand/forecast) | ✅ Done |
| 13 | Error handling (explicit, never silent zero) | ✅ Done |
| 14–18 | Test suite (74 tests) | ✅ Done |
| 22 | Platform integration readiness | ✅ Done |

### Pending Phases (next)

| Phase | Description | Priority |
|---|---|---|
| 19 | Real Prometheus demand provider | After Checkpoint 3 |
| 20 | Member 1 TrafficAssessment integration | After Checkpoint 3 |
| 21 | Real environment validation | After Checkpoint 3 |
| 23 | Final handoff (already done partially) | Ongoing |

---

## 5. Member 2 — Architecture

```
services/demand-intelligence/
├── app/
│   ├── main.py                    ← FastAPI app factory
│   ├── logging.py                 ← Structured JSON logging middleware
│   ├── errors.py                  ← Explicit error types
│   ├── config/
│   │   └── settings.py            ← SERVICE_VERSION, CONTRACT_VERSION, MODEL_VERSION
│   ├── models/
│   │   └── demand.py              ← DemandObservation, ForecastRequest, DemandForecast
│   ├── providers/
│   │   ├── base.py                ← Abstract DemandProvider interface
│   │   ├── mock_provider.py       ← MockDemandProvider (sinusoidal deterministic)
│   │   └── static_provider.py    ← StaticObservationProvider (inline observations)
│   ├── engine/
│   │   ├── preprocessor.py        ← Validate, sort, deduplicate, statistics
│   │   └── forecaster.py          ← RWMA + trend + confidence → DemandForecast
│   ├── services/
│   │   └── forecaster.py          ← DemandForecastingService (provider selection + orchestration)
│   ├── api/
│   │   └── v1/
│   │       └── endpoints.py       ← POST /api/v1/demand/forecast
│   └── mock/
│       └── generator.py           ← Legacy mock (preserved, unused in production path)
└── tests/
    ├── test_demand_observations.py   ← Domain model tests
    ├── test_preprocessor.py          ← Preprocessor unit tests
    ├── test_forecasting_engine.py    ← Engine unit tests (bounds, confidence, trend, determinism)
    ├── test_mock_provider.py         ← Mock provider tests
    ├── test_error_handling.py        ← Error handling integration tests
    ├── test_traceability.py          ← Trace ID / metadata tests
    ├── test_demand_api.py            ← Full API integration tests
    ├── test_health.py                ← Health/ready/version endpoint tests
    └── test_contract_conformance.py  ← JSON Schema conformance test
```

---

## 6. Forecasting Algorithm

**Model:** `demand-v1` — Recency-Weighted Moving Average + Linear Trend Projection

1. Validate/preprocess observations (sort oldest→newest, deduplicate, reject negative RPS)
2. Compute time-aware exponentially weighted mean (decay=0.85 per 30s)
3. Compute linear regression slope over full series (trend)
4. Project forward: `predicted = weighted_mean + slope × horizon_seconds` (if ≥5 observations AND time_span ≥ 120s, slope capped to ±10.0 RPS/s)
5. Prediction interval: `±1.5 × std_dev` around point estimate
6. Confidence: geometric mean of sample-count confidence, variance confidence, and horizon ratio
7. Build `DemandForecast` with frozen contract fields

**Minimum observations:** 2 (raises `InsufficientDataError` if fewer)
**Trend activation threshold:** 5 observations AND 120s time span

---

## 7. Key Design Decisions

| Decision | Rationale |
|---|---|
| Inline observations in ForecastRequest | Enables Member 3 to supply telemetry directly without building a separate client; enables deterministic integration testing |
| `InsufficientDataError` vs zero RPS | Explicitly different: "no data" ≠ "zero demand" |
| `StaticObservationProvider` vs `MockDemandProvider` | Clean provider selection without coupling API to provider type |
| Engine separated from service layer | Engine independently testable without HTTP stack |
| `model_construct` in tests for negative RPS | Defence in depth: Pydantic guards at model layer; preprocessor guards at engine layer |
| Mocks preserved | `app/mock/generator.py` kept — rule: mocks stay |

---

## 8. Test Results

```
Command: python -m pytest services/demand-intelligence/tests -v -o "pythonpath=services/demand-intelligence"
Result:  74 passed, 0 failed
```

Full project: `python run_tests.py`
```
Demo API                    PASSED
Traffic Intelligence        PASSED
Demand Intelligence         PASSED  (74 tests)
Platform & Decision Engine  PASSED
ALL 4 SERVICE TEST SUITES PASSED
```

---

## 9. Member 3 — Current State

**Branch:** `member3/platform`  
**Phase:** 3A complete, 3B pending  
**Status:** Waiting for Member 2 real `DemandForecast` to replace `FakeDemandForecast`

Member 3 has:
- Decision Engine (deterministic logic)
- Policy Guardrails
- ResourceState
- DecisionContext schema conformance test

Member 3 needs from Member 2:
- [x] `POST /api/v1/demand/forecast` endpoint — **DONE**
- [x] `DemandForecast` v1.0.0 response — **DONE**
- [x] `confidence` field populated — **DONE**
- [x] `predicted_legitimate_rps` populated — **DONE**
- [x] Trace ID propagation — **DONE**

---

## 10. Checkpoints

| Checkpoint | Description | Status |
|---|---|---|
| 0 | Architecture / contract freeze | ✅ |
| 1 | Domain models ready | ✅ |
| 2 | Provider / API readiness | ✅ |
| 3 | First cross-module integration | 🔄 Ready from M2 side; M3 needs to wire adapter |
| 4 | DecisionContext assembly | ⏳ |
| 5 | Cross-module failure handling | ⏳ |
| 6 | Traceability | ✅ M2 side |
| 7–12 | Full integration, shadow mode, experiment | ⏳ |

---

## 11. Immediate Next Steps for Member 2

After Checkpoint 3 (M3 integration is confirmed):

1. **Phase 19** — Real demand provider  
   - Create `PrometheusDemandProvider` implementing `DemandProvider`
   - Replace `MockDemandProvider` as default when `PROMETHEUS_URL` is configured
   - Keep mock as fallback

2. **Phase 20** — Member 1 integration  
   - Consume `TrafficAssessment.legitimacy_score` to weight demand observations
   - Only count observations from periods where `legitimacy_score >= threshold`

3. **Confidence calibration** — Tune constants once real data is available

4. **Phase 23 final handoff** — Update `docs/member2_handoff.md` with real Prometheus data

---

## 12. Engineering Rules (Do Not Violate)

1. **Contracts are frozen** — never modify `contracts/**` files without team agreement
2. **Mocks stay** — do not delete `MockDemandProvider` when real provider is added
3. **No autonomous actuation** — `dry_run=true` everywhere
4. **Failures are explicit** — never convert provider failure to zero demand
5. **Module boundaries clean** — Member 2 does not import Member 3 code
6. **Tests must pass before commit** — run `run_tests.py` before any push
7. **Update this file** — every agent must update `docs/implementation_context.md` after completing work
