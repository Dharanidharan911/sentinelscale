# SentinelScale — Stage F4: End-to-End Dynamic Scenario Suite

## 1. Overview & Objective

Stage F4 establishes the end-to-end data provenance and behavioral validation of SentinelScale across all four microservices and internal components under **dynamically generated HTTP traffic**.

The entire flow operates without mock data fabrication:

```text
Generated HTTP Traffic
        ↓
Demo API (FastAPI)
        ↓
F1 Traffic Harness (AsyncTrafficGenerator → TelemetryCollector)
        ↓
Member 1 — Traffic Intelligence (`POST /api/v1/traffic/assess`)
        ↓ TrafficAssessment
F2 Demand Observation Accumulator (Validation + Security Gate + SQLite)
        ↓ DemandObservation[]
F3 Demand Intelligence Client (`POST /api/v1/demand/forecast`)
        ↓
Member 2 — Demand Intelligence (demand-v1 RWMA + Trend Forecaster)
        ↓ DemandForecast
Member 3 ContextAggregatorService
        ↓
DecisionContext (v1.0.0)
        ↓
Baseline HPA + DecisionEngine + PolicyGuardrails
        ↓
ScalingDecision (v1.0.0, dry_run=true, shadow_mode=true)
        ↓
HPA vs SentinelScale Comparative Evaluator
```

---

## 2. Dynamic Scenario Results & Provenance Matrix

| Scenario | Requests | Observed RPS | M1 Risk | M1 Classification | Legitimate RPS | F2 Accepted | M2 Observations | M2 Forecast | HPA Replicas | SentinelScale Replicas | Evaluator Category |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Scenario A: Steady Legitimate** | 250 | 50.0 | 0.02 | `LEGITIMATE` | 50.0 | **YES (1 obs)** | 1 obs | 50.0 RPS | 4 | 2 | `SCALE_DOWN_DIFFERENCE` / `ALIGNED` |
| **Scenario B: Flash Crowd Surge** | 1250 | 250.0 | 0.08 | `LEGITIMATE` | 250.0 | **YES (1 obs)** | 1 obs | 250.0 RPS | 4 | 2–4 | `ALIGNED` / `SENTINELSCALE_PROACTIVELY_SCALES` |
| **Scenario C: Hostile L7 Flood** | 1500 | 300.0 | 0.85 | `MALICIOUS` | 45.0 | **NO (BLOCKED)** | 0 attack obs (1 baseline seed) | 50.0 RPS | 6–8 | 4 (HOLD) | `SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE` |
| **Scenario D: Mixed Traffic** | 750 | 150.0 | 0.48 | `LEGITIMATE`/`SUSPICIOUS` | 90.0 (60%) | **YES (legitimate only)** | 1 obs (90.0 RPS) | 90.0 RPS | 4 | 2–4 | `ALIGNED` |

---

## 3. Key Provenance & Security Findings

1. **Hostile Flood Rejected at Security Gate**:
   - In Scenario C (Hostile L7 Flood), M1 flagged `risk_score = 0.85` and `classification = MALICIOUS`.
   - Stage F2 Accumulator rejected the assessment (`record_traffic_assessment` returned `None`).
   - SQLite demand store contained strictly the legitimate baseline seed observation; **zero attack flood observations entered the demand history**.
2. **Flash Crowd Distinguishes Volume from Malice**:
   - In Scenario B, high traffic volume (250 RPS, 5x baseline) across 100 distinct client IPs with browser User-Agents resulted in `risk_score = 0.08` and top signal `organic_demand_surge`.
   - SentinelScale confirmed that heavy traffic alone is not treated as an attack.
3. **Mixed Workload Separation**:
   - In Scenario D, M1 separated total 150 RPS into 90 RPS legitimate vs 60 RPS suspicious scraper traffic.
   - F2 accumulated only the legitimate 90 RPS estimate into demand history.
4. **Dynamic Forecasting**:
   - M2 produced statistically grounded forecasts that grew when legitimate demand increased (e.g. 50 RPS → 250 RPS) and remained stable when demand remained baseline.
5. **Evaluator Comparative Economics**:
   - During attack conditions with 95% CPU utilization, baseline HPA scaled to 6–8 pods while SentinelScale held at 4 pods, preventing 2–4 unnecessary pod allocations (`SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE`).

---

## 4. Test Suite Execution Summary

Dedicated suite: [`services/platform/tests/test_stage_f4_dynamic_scenarios.py`](file:///c:/SentinelScale/services/platform/tests/test_stage_f4_dynamic_scenarios.py)

- `test_scenario_a_steady_legitimate_full_pipeline` → **PASSED**
- `test_scenario_b_legitimate_flash_crowd_distinguished_from_attack` → **PASSED**
- `test_scenario_c_hostile_l7_flood_rejected_by_f2_demand_gate` → **PASSED**
- `test_scenario_d_mixed_traffic_preserves_legitimate_provenance` → **PASSED**
- `test_m2_observation_dispatch_data_provenance` → **PASSED**
- `test_m2_dynamic_forecast_behavior_under_varying_demand` → **PASSED**
- `test_decision_context_contains_m1_and_m2_outputs` → **PASSED**
- `test_evaluator_comparative_correctness_on_attack_suppression` → **PASSED**
- `test_trace_id_continuity_across_full_f4_pipeline` → **PASSED**
- `test_safety_invariants_zero_kubernetes_mutations` → **PASSED**

Full Repository Test Runner (`python run_tests.py`):
- Demo API: **9 passed**
- Traffic Intelligence: **5 passed**
- Demand Intelligence: **100 passed**
- Platform & Decision Engine: **232 passed, 2 skipped**
- **Total: 346 tests passed (2 skipped)**

---

## 5. Safety Invariants Status

- `dry_run = True` is unconditionally enforced.
- `shadow_mode = True` is active.
- `SENTINEL_AUTONOMOUS_ACTIONS_ENABLED = False`.
- Zero Kubernetes cluster mutations or `kubectl` subprocess calls occurred.

