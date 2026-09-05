# SentinelScale — Stage F5: Comparative HPA vs SentinelScale Evaluation

## 1. Overview & Evaluation Objective

Stage F5 executes a systematic comparative evaluation between standard reactive Kubernetes Horizontal Pod Autoscaler (HPA) and SentinelScale's security-aware resource intelligence platform across the four dynamic traffic scenarios established in Stage F4.

The core question evaluated is:
> **Across realistic traffic scenarios, when does SentinelScale make a different decision from baseline HPA, why does it differ, and what measurable operational benefit results?**

The evaluation runs directly against the live integrated data path:
```text
Generated HTTP Traffic (Demo API)
        ↓
F1 Traffic Harness (Collector)
        ↓
Member 1 Traffic Intelligence (TrafficAssessment)
        ↓
F2 Demand Observation Accumulator (Security Gate)
        ↓
Member 2 Demand Intelligence (DemandForecast)
        ↓
Member 3 Context Aggregator (DecisionContext)
        ↓
Baseline HPA + DecisionEngine + PolicyGuardrails (ScalingDecision)
        ↓
DefaultHPAEvaluationService (EvaluationResult)
```

---

## 2. Quantitative Comparative Matrix

| Scenario | Observed Total RPS | M1 Legitimate RPS | M1 Risk | Classification | M2 Forecast RPS | Resource CPU | Baseline HPA Pods | SentinelScale Pods | Replica Delta | Evaluation Category | Recommendation Difference | Pod-Hours Saved / Hr |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :--- | :---: |
| **Scenario A: Steady Legitimate** | 50.0 | 50.0 | 0.02 | `LEGITIMATE` | 50.0 | 50% | 4 | 2 | -2 | `SCALE_DOWN_DIFFERENCE` | `SENTINELSCALE_FEWER_PODS` | 2.0 |
| **Scenario B: Flash Crowd Surge** | 250.0 | 250.0 | 0.08 | `LEGITIMATE` | 250.0 | 55% | 4 | 2–4 | 0 | `ALIGNED` / `SENTINELSCALE_PROACTIVELY_SCALES` | `EQUAL` | 0.0 |
| **Scenario C: Hostile L7 Flood** | 300.0 | 45.0 | 0.85 | `MALICIOUS` | 50.0 | 95% | 6–8 | 4 | -2 to -4 | `SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE` | `SENTINELSCALE_FEWER_PODS` | 2.0–4.0 |
| **Scenario D: Mixed Traffic** | 150.0 | 90.0 | 0.48 | `LEGITIMATE` | 90.0 | 55% | 4 | 2–4 | 0 to -2 | `ALIGNED` / `SCALE_DOWN_DIFFERENCE` | `EQUAL` / `SENTINELSCALE_FEWER_PODS` | 0.0–2.0 |

*Note: Pod-hours saved are calculated per running hour at steady state based on authoritative replica counts (`max(0, HPA_pods - SentinelScale_pods)`).*

---

## 3. Key Findings Across Dimensions

### 1. Security Awareness & EDoS Overprovisioning Prevention (Scenario C)
- **Problem with Baseline HPA**: When 300 RPS hostile flood traffic hits the service causing CPU utilization to spike to 95%, reactive HPA blindly scales out to 6–8 pods, consuming cloud budget for attacker traffic.
- **SentinelScale Behavior**: Detects `traffic_risk = 0.85`, classifies traffic as `MALICIOUS`, prevents attack traffic from entering historical demand store, and observes that legitimate demand (45–50 RPS) easily fits in current capacity (1400 RPS).
- **Outcome**: SentinelScale enforces a security `HOLD` at 4 pods, saving **2.0 to 4.0 pod-hours per hour** (`SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE`).

### 2. Legitimate Demand Responsiveness (Scenario B)
- **Concern**: Ensure SentinelScale does not suppress scaling during real traffic surges.
- **SentinelScale Behavior**: High volume (250 RPS) across 100 distributed client IPs with valid browser User-Agents is recognized with `risk_score = 0.08` (`LEGITIMATE`) and signal `organic_demand_surge`.
- **Outcome**: Legitimate surge is accepted into demand history, projected by Module 2, and allocated appropriate pod capacity (`ALIGNED` / `SENTINELSCALE_PROACTIVELY_SCALES`).

### 3. Normal Baseline Right-Sizing (Scenario A)
- **SentinelScale Behavior**: With 50 RPS steady legitimate demand, SentinelScale calculates that 2 pods (700 RPS capacity) are sufficient rather than maintaining 4 idle pods.
- **Outcome**: Evaluator marks `SCALE_DOWN_DIFFERENCE`, identifying 2.0 pod-hours/hr in baseline right-sizing efficiency.

### 4. Mixed Traffic Separation (Scenario D)
- **SentinelScale Behavior**: Blended traffic (90 RPS legitimate + 60 RPS scraper) is decomposed. Demand forecast is strictly anchored to the 90 RPS legitimate estimate.

---

## 4. Aggregate Evaluation Statistics

- **Total Scenarios Evaluated**: 4
- **Scenarios with SentinelScale < HPA (Efficiency / Protection)**: 2 (Scenario A, Scenario C)
- **Scenarios with SentinelScale == HPA (Aligned Operation)**: 2 (Scenario B, Scenario D)
- **Scenarios with SentinelScale > HPA**: 0 (Capacity was sufficient in Scenario B)
- **Hostile Traffic Entry into Demand Store**: **0 requests / 0%**
- **Average Pod Savings during Attack**: **2 to 4 pods (25% to 50% infrastructure reduction)**

---

## 5. Test Suite Verification

Dedicated Test Suite: [`services/platform/tests/test_stage_f5_comparative_evaluation.py`](file:///c:/SentinelScale/services/platform/tests/test_stage_f5_comparative_evaluation.py)

- `test_scenario_a_steady_legitimate_comparative_evaluation` → **PASSED**
- `test_scenario_b_legitimate_flash_crowd_comparative_evaluation` → **PASSED**
- `test_scenario_c_hostile_l7_flood_attack_suppression_evaluation` → **PASSED**
- `test_scenario_d_mixed_traffic_comparative_evaluation` → **PASSED**
- `test_evaluation_records_contain_genuine_m1_m2_provenance` → **PASSED**
- `test_replica_delta_and_recommendation_difference_conformance` → **PASSED**
- `test_pod_hours_saved_calculation_integrity` → **PASSED**
- `test_no_raw_attack_traffic_enters_demand_history` → **PASSED**
- `test_trace_id_retained_in_evaluation_result` → **PASSED**
- `test_safety_invariants_preserved_in_f5` → **PASSED**

Full Repository Test Runner (`python run_tests.py`):
- Demo API: **9 passed**
- Traffic Intelligence: **5 passed**
- Demand Intelligence: **100 passed**
- Platform & Decision Engine: **242 passed, 2 skipped**
- **Total: 356 tests passed, 2 skipped across all 4 services**

---

## 6. Safety Invariants & Scope Boundaries

- `dry_run = True` and `shadow_mode = True` enforced across all evaluations.
- Zero autonomous cluster mutations or `kubectl` subprocess calls.
- Measured scenario-level comparative results reflect deterministic test environments; actual cloud cost savings in production will vary depending on cluster node instance sizing, pod startup latencies, and attack duration.

