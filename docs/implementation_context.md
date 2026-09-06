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

### Status: ✅ INTEGRATION READY (Checkpoint 3) + Prometheus provider available

### Completed Phases

| Phase | Description | Status |
|---|---|---|
| 0 | Contract & architecture freeze | ✅ Done |
| 1 | Provider abstraction | ✅ Done |
| 2 | DemandObservation domain model | ✅ Done |
| 3 | Historical data window via MockDemandProvider | ✅ Done |
| 4 | Forecast Quality Hardening (irregular intervals, bounds) | ✅ Done |
| 5 | Configurable Forecasting (Settings migration) | ✅ Done |
| 19 | Real Prometheus demand provider (opt-in adapter) | ✅ Done |
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
| 23 | M2-4: Feature engineering (12-feature leakage-safe extractor) | ✅ Done |
| 24 | M2-5: ML forecasting candidate (demand-ml-v1 Ridge regression) | ✅ Done |
| 25 | M2-6: Model benchmarking suite & synthetic evaluation report | ✅ Done |
| 26 | M2-7: Configurable provider & model architecture | ✅ Done |
| 27 | M2-8: DemandForecast Integration & zero-RPS preservation | ✅ Done |
| 28 | M2-9: Horizon & regularity dilated prediction intervals | ✅ Done |
| 29 | M2-10: Calibrated confidence scoring | ✅ Done |
| 30 | M2-11: Explicit failure & transparent ML-to-baseline fallback | ✅ Done |
| 31 | M2-12: Data quality intelligence (completeness, regularity, staleness) | ✅ Done |
| 32 | M2-13: Deterministic seasonality detection & harmonic adjustment | ✅ Done |
| 33 | M2-14: Forecast explainability engine & response headers | ✅ Done |

### Pending Phases (next)

| Phase | Description | Priority |
|---|---|---|
| 34 | Member 1 TrafficAssessment integration | After Checkpoint 3 |
| 35 | Real environment live cluster validation | After Checkpoint 3 |
| 36 | Member 3 downstream consumption | Ready for integration |

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
│   │   ├── prometheus_provider.py ← PrometheusDemandProvider (real telemetry)
│   │   └── static_provider.py    ← StaticObservationProvider (inline observations)
│   ├── engine/
│   │   ├── preprocessor.py        ← Validate, sort, deduplicate, statistics
│   │   ├── features.py            ← 12-feature time-series extractor (M2-4)
│   │   ├── forecaster.py          ← RWMA + trend + intervals + confidence (demand-v1)
│   │   ├── ml_forecaster.py       ← Regularized Ridge ML forecaster (demand-ml-v1)
│   │   ├── data_quality.py        ← Data quality assessor & rating (M2-12)
│   │   ├── seasonality.py         ← Autocorrelation peak & harmonic adjustment (M2-13)
│   │   └── explainability.py      ← Multi-tag explainability engine (M2-14)
│   ├── services/
│   │   └── forecaster.py          ← DemandForecastingService (provider & model selection)
│   ├── api/
│   │   └── v1/
│   │       └── endpoints.py       ← POST /api/v1/demand/forecast (v1.0.0 + headers)
│   └── mock/
│       └── generator.py           ← Legacy mock (preserved)
├── benchmarks/
│   ├── benchmark_suite.py         ← Deterministic walk-forward benchmark (M2-6)
│   └── BENCHMARK_REPORT.md        ← Measured metrics across 6 synthetic scenarios
└── tests/                         ← 159 passing tests (100% pass rate)
```

---

## 6. Forecasting Algorithm & Capabilities

**Baseline Model:** `demand-v1` — Recency-Weighted Moving Average + Linear Trend + Seasonality
**Candidate ML Model:** `demand-ml-v1` — Feature-Engineered Ridge Regression with safe fallback

1. Validate/preprocess observations (sort oldest→newest, deduplicate, reject negative RPS)
2. Assess data quality (completeness, cadence regularity, staleness, noise-to-signal ratio)
3. Compute time-aware exponentially weighted mean (decay=0.85 per 30s)
4. Compute linear regression slope over full series (trend capped to ±10.0 RPS/s)
5. Detect seasonality via autocorrelation peaks; apply harmonic adjustment if ≥2 periods present
6. Prediction interval: horizon and regularity dilated bounded interval:
   $\sigma_{\text{eff}} = \sigma \sqrt{1 + h / \max(T, 30)} \times (1 + 0.5(1 - \text{regularity}))$
7. Confidence: multi-factor calibrated score combining sample count, CV, horizon ratio, regularity, and data quality
8. Explainability: deterministic reason tags (trend, volatility, quality, uncertainty, model) attached to response headers (`X-Forecast-Explanation`, `X-Forecast-Quality`) and structured logging
9. Build `DemandForecast` with frozen contract fields v1.0.0

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
Result:  159 passed, 0 failed
```

Full project: `python run_tests.py`
```
Demo API                    PASSED
Traffic Intelligence        PASSED
Demand Intelligence         PASSED  (159 tests)
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

1. **Phase 20** — Member 1 integration
   - Consume `TrafficAssessment.legitimacy_score` to weight demand observations
   - Only count observations from periods where `legitimacy_score >= threshold`

2. **Confidence calibration** — Tune constants once real data is available

3. **Phase 23 final handoff** — Update `docs/member2_handoff.md` with real Prometheus data

---

## 13. Member 2 Phase 19 — Prometheus Provider (2026-09-04)

**Starting head:** `4f3612869141641b1062491346c098d36696272d`
**Previous stable version:** `member2-v1.2-configurable-forecasting`
**Contract:** `DemandForecast` v1.0.0 remains frozen and unchanged.

- Added `PrometheusDemandProvider`, an isolated `/api/v1/query_range` adapter.
- It emits ordered `DemandObservation` samples, combines equal timestamps from multi-series results, and uses no forecast-engine internals.
- Network, HTTP, JSON, shape, timestamp, and RPS failures become `ProviderUnavailableError` (HTTP 503), never zero demand. Empty successful results remain no data and flow to the existing insufficient-data error.
- Service selection is opt-in: an injected provider and inline observations retain precedence; `PROMETHEUS_URL` selects Prometheus; otherwise the deterministic mock remains the fallback.
- Added validated `PROMETHEUS_URL`, `PROMETHEUS_QUERY`, `PROMETHEUS_STEP_SECONDS`, and `PROMETHEUS_TIMEOUT_SECONDS` settings. The default metric query requires deployment instrumentation; the repository currently does not emit it.
- Added `app/providers/prometheus_provider.py` and `tests/test_prometheus_provider.py`; updated provider exports, service selection, settings, Compose/env example, README, and handoff.
- Focused test: `python -m pytest services/demand-intelligence/tests/test_prometheus_provider.py -v -o "pythonpath=services/demand-intelligence"` → **9 passed**.
- Regression: `python -m pytest services/demand-intelligence/tests -v -o "pythonpath=services/demand-intelligence"` → **87 passed**, 3 third-party deprecation warnings.

**Next phase:** Phase 20, TrafficAssessment integration, after confirming an agreed upstream contract boundary; do not import Member 1 internals.

---

## 14. Member 2 Data Quality Hardening (2026-09-05)

**Starting head:** `7ae3c3b33809ae040d94d43a10d4b52be122ba5e`
**Previous stable version:** `member2-v1.3-prometheus-provider`
**Contract:** `DemandForecast` v1.0.0 remains frozen and unchanged.

- `DemandObservation` now rejects non-finite timestamps/RPS and timestamps more than the configured future clock skew.
- `preprocess_observations` repeats those validations for provider or test inputs that bypass Pydantic, preserving defence in depth.
- `OBSERVATION_MAX_FUTURE_SKEW_SECONDS` defaults to 60 seconds and is non-negative validated. Historical replay remains supported; no global staleness cutoff was introduced because source freshness belongs to the provider/request context.
- Invalid observations remain explicit `InvalidObservationError` / HTTP 422 semantics. Valid 0 RPS observations still mean genuine zero demand; no-data and provider failures remain distinct.
- Added `tests/test_data_quality.py` covering NaN, infinities, future timestamps, and bypassed model validation.
- Focused command: `python -m pytest services/demand-intelligence/tests/test_data_quality.py services/demand-intelligence/tests/test_preprocessor.py services/demand-intelligence/tests/test_demand_observations.py -v -o "pythonpath=services/demand-intelligence"` → **33 passed**.
- Member 2 regression: `python -m pytest services/demand-intelligence/tests -v -o "pythonpath=services/demand-intelligence"` → **99 passed**, 3 third-party deprecation warnings.

**Next phase:** confidence quality / sampling-regularity semantics. Phase 20 TrafficAssessment integration remains deferred pending an agreed upstream contract boundary. The v1.3 branch and tag are not yet published to origin; an attempted push was declined because the remote has not been explicitly trusted for this session.

---

## 15. Member 2 Confidence and Observability Hardening (2026-09-05)

- Confidence now incorporates deterministic sampling regularity: irregular valid observations lower confidence rather than becoming invalid data.
- Added validated `FORECAST_REGULARITY_CONFIDENCE_SCALE` with a safe default.
- Successful forecasts emit structured diagnostics for provider, observation count, horizon, trace ID, and elapsed time; the frozen `DemandForecast` output remains unchanged.
- Member 2 tests: `python -m pytest services/demand-intelligence/tests -q -o "pythonpath=services/demand-intelligence"` → **100 passed**.
- Next local work is production-readiness review/documentation. TrafficAssessment ingestion remains blocked on an agreed contract-level input boundary and is not implemented through Member 1 internals.

---

## 16. Member 2 Completion and Integration Readiness Review (2026-09-05)

**Current state:** independent Member 2 implementation is feature-complete for
the current architecture.

- Branch: `member2/demand-intelligence`
- Latest local milestone: `member2-v1.5-confidence-observability`
- Latest local commit: `9bd5bf4`
- Contract: `DemandForecast` v1.0.0, frozen and unchanged
- Verification: 100 Member 2 tests passed; `python run_tests.py` passed all four service suites.
- Git: working tree was clean at review. Remote publishing is not authorized; v1.3 through v1.5 remain local only.

### Classification of Remaining Work

- **Completed:** deterministic forecasting, bounds, configuration, provider abstraction, mock/Prometheus providers, data validation, confidence regularity, diagnostics, HTTP API, traceability, health endpoints, contract testing, and documentation.
- **Integration dependency:** mapping Member 1 `TrafficAssessment` (`legitimate_rps_estimate`, `legitimacy_score`) into a historical `DemandObservation` ingestion boundary. No approved API/contract mapping exists, so Member 2 must not invent one or import Member 1 internals.
- **Integration dependency:** Member 3 must invoke the existing Member 2 HTTP endpoint and map the valid `DemandForecast` response into its `DecisionContext`.
- **Deployment dependency:** Prometheus must expose a deployment-specific RPS metric/query. Repository services do not emit the default query metric.
- **Optional future enhancement:** seasonality/stateful model calibration with production data; not required for the explainable deterministic v1 model.

**Exact next action:** Member 3 should integrate its `DemandForecastClient` with `POST /api/v1/demand/forecast`, passing contract-approved observations and the shared trace ID. No remote push is authorized.

---

## 17. Member 2 IC-4 Milestone — Feature Engineering, ML Candidate, Benchmark & Provider Architecture (2026-09-06)

**Contract:** `DemandForecast` v1.0.0 remains frozen and unchanged.

- **M2-4 Feature Engineering (`app/engine/features.py`)**:
  - Implemented `DemandFeatureExtractor` extracting 12 canonical, leakage-safe features (`recent_demand`, `lag_1`, `lag_2`, `rolling_mean_short`, `rolling_mean_full`, `rolling_std_full`, `trend_slope`, `rate_of_change`, `acceleration`, `sampling_regularity`, `time_span_seconds`, `horizon_ratio`).
  - Strict invariants: strictly $t \le t_{last}$ (zero future leakage), deterministic, stable named and vector ordering, explicit `InsufficientDataError` when $N < 4$.
- **M2-5 ML Forecasting Model (`app/engine/ml_forecaster.py`)**:
  - Implemented `MLDemandForecaster` with model version identity `"demand-ml-v1"`.
  - Regularized closed-form Ridge linear regression solver ($\alpha=1.0$), non-negative clamping, bounds invariant ($\text{lower} \le \text{predicted} \le \text{upper}$), and confidence scoring.
  - Failure-safe fallback: when $N < 4$ or upon numerical anomaly, gracefully delegates to baseline RWMA (`demand-v1`) with structured fallback logging.
- **M2-6 Benchmark Suite (`benchmarks/benchmark_suite.py`, `tests/test_forecast_benchmark.py`)**:
  - Executed reproducible comparison across 6 synthetic scenarios (steady growth, decline, flat, sinusoidal, flash surge, noisy).
  - Actual measured results:
    - Baseline (`demand-v1`): Overall MAE = 54.19 RPS, RMSE = 65.94 RPS, Latency = 0.1702 ms, Interval Coverage = 83.3%.
    - ML Candidate (`demand-ml-v1`): Overall MAE = 180.43 RPS, RMSE = 362.66 RPS, Latency = 1.6652 ms, Interval Coverage = 33.3%.
    - Decision: ML candidate exhibits superior accuracy on smooth linear trends but overshoots on step-surge discontinuities. Baseline retained as the preferred default; ML retained as configurable opt-in.
- **M2-7 Provider Architecture (`app/config/settings.py`, `app/services/forecaster.py`)**:
  - Added `FORECAST_MODEL` (default: `"baseline"`, opt-in: `"ml"`) and `ML_RIDGE_ALPHA` (default: 1.0).
  - Extended `DemandForecastingService` to orchestrate model selection and log `model_version`.
  - Exported all providers from `app/providers/__init__.py`.
- **Test Results**:
  - Focused: 121 Member 2 tests passed (`pytest services/demand-intelligence/tests`).
  - Full repo: `python run_tests.py` passed all 4 service test suites cleanly.

---

## 12. Engineering Rules (Do Not Violate)

1. **Contracts are frozen** — never modify `contracts/**` files without team agreement
2. **Mocks stay** — do not delete `MockDemandProvider` when real provider is added
3. **No autonomous actuation** — `dry_run=true` everywhere
4. **Failures are explicit** — never convert provider failure to zero demand
5. **Module boundaries clean** — Member 2 does not import Member 3 code
6. **Tests must pass before commit** — run `run_tests.py` before any push
7. **Update this file** — every agent must update `docs/implementation_context.md` after completing work

