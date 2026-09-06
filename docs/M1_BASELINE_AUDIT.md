# SentinelScale — Traffic Intelligence (Module 1) Baseline Audit

## 1. Executive Summary
This document provides a comprehensive audit of the baseline implementation of **Module 1: Traffic Intelligence** (`services/traffic-intelligence`) within the SentinelScale repository as of Phase M1-0. 

The audit establishes the current architectural structure, pipeline mechanics, feature extraction capabilities, scoring logic, classification logic, API conformance, test coverage, and benchmark readiness prior to introducing Machine Learning (such as Isolation Forests).

---

## 2. Current Architecture
- **Service Root**: `services/traffic-intelligence/`
- **Application Framework**: FastAPI (running on port `8001` via Uvicorn).
- **Service Role**: Telemetry ingestion, traffic behavior analysis, burst/spike anomaly detection, security risk assessment, legitimate vs suspicious classification, and confidence scoring.
- **Architectural Boundary**: Traffic Intelligence produces evidence only (`TrafficAssessment` contract). It does not perform scaling actions, HPA actuation, demand forecasting (M2), or policy arbitration (M3).
- **Service Version**: `0.1.0`
- **Model Version**: `traffic-rules-v1`
- **Contract Version**: `1.0.0`
- **Downstream Consumer**: Module 3 (`services/platform/app/clients/traffic_client.py`).

---

## 3. Existing Pipeline
The internal execution path for an assessment request is structured cleanly in `app/pipeline/`:

```
AssessmentRequest (with optional telemetry & trace_id)
                      ↓
  FeatureExtractor (app/pipeline/features.py)
                      ↓ (ExtractedTrafficFeatures)
  BurstDetector (app/pipeline/burst_detector.py)
                      ↓ (BurstDetectionResult)
  TrafficScorer (app/pipeline/scorer.py)
                      ↓ (ScoreResult: risk, legitimacy, confidence, RPS partitions)
  TrafficClassifier (app/pipeline/classifier.py)
                      ↓ (ClassificationResult: category, top_signals)
  TrafficIntelligenceEngine (app/pipeline/engine.py)
                      ↓
  TrafficAssessment (Canonical Contract v1.0.0)
```

If `telemetry` is omitted in `AssessmentRequest`, `TrafficIntelligenceEngine` evaluates a default representative telemetry payload to preserve 100% backward compatibility with upstream callers (such as Platform's client).

---

## 4. Existing Features
From `app/pipeline/features.py` and `ExtractedTrafficFeatures`:

| Feature Name | Type | Unit | Range | Source / Derivation |
| :--- | :--- | :--- | :--- | :--- |
| `total_rps` | Float | req/sec | $\ge 0.0$ | `telemetry.total_rps` |
| `burst_ratio` | Float | ratio | $\ge 0.0$ | $\text{total\_rps} / \text{baseline\_rps}$ (defaults to 1.0 if baseline missing) |
| `error_rate` | Float | ratio | $[0.0, 1.0]$ | $(\text{status\_4xx} + \text{status\_5xx}) / \text{total\_requests}$ |
| `ip_concentration` | Float | ratio | $[0.0, 1.0]$ | `telemetry.top_ip_ratio` |
| `ua_anomaly_ratio` | Float | ratio | $[0.0, 1.0]$ | `telemetry.non_standard_ua_ratio` |
| `single_endpoint_ratio`| Float | ratio | $[0.0, 1.0]$ | `telemetry.single_endpoint_ratio` |
| `has_telemetry` | Bool | boolean | True/False | Indicates if telemetry payload was provided |
| `data_completeness` | Float | ratio | $[0.0, 1.0]$ | Proportion of optional telemetry fields provided (5 fields evaluated) |

---

## 5. Existing Scoring Logic
Implemented in `TrafficScorer.calculate_scores` (`app/pipeline/scorer.py`):
1. **Component Risk Penalties**:
   - `ip_risk = min(1.0, ip_concentration / IP_CONCENTRATION_CRITICAL)` (threshold: 0.70, weight: 0.35)
   - `ua_risk = min(1.0, ua_anomaly_ratio / UA_ANOMALY_CRITICAL)` (threshold: 0.65, weight: 0.30)
   - `error_risk = min(1.0, error_rate / ERROR_RATE_HIGH)` (threshold: 0.35, weight: 0.20)
   - `burst_risk`: 0.0 (Nominal), 0.35 (Elevated $\ge 1.75$), 0.70 (Spike $\ge 2.5$), 1.0 (Extreme $\ge 4.0$) (weight: 0.15)
2. **Weighted Risk Aggregation**:
   $$\text{raw\_risk} = 0.35 \times \text{ip\_risk} + 0.30 \times \text{ua\_risk} + 0.20 \times \text{error\_risk} + 0.15 \times \text{burst\_risk}$$
3. **Safety Heuristic Clamps**:
   - Elevated attack clamp: If $\text{ip\_concentration} \ge 0.70$ and $\text{ua\_anomaly\_ratio} \ge 0.35$, $\text{raw\_risk} \ge 0.85$.
   - Clean traffic clamp: If $\text{ip\_concentration} \le 0.15$, $\text{ua\_anomaly\_ratio} \le 0.05$, and $\text{error\_rate} \le 0.05$, $\text{raw\_risk} \le 0.20$.
   - Risk score bounded $[0.0, 1.0]$.
4. **Legitimacy Score**:
   $$\text{legitimacy} = 0.50 \times (1.0 - \text{risk\_score}) + 0.20 \times (1.0 - \text{ip\_concentration}) + 0.20 \times (1.0 - \text{ua\_anomaly\_ratio}) + 0.10 \times (1.0 - 2 \times \text{error\_rate})$$
   Bounded $[0.0, 1.0]$.
5. **Confidence Score**:
   Combines observation window duration ($\min(1.0, \text{window\_seconds} / 60)$) and `data_completeness`:
   $$\text{confidence} = 0.50 \times \text{duration\_factor} + 0.50 \times \text{data\_completeness}$$

---

## 6. Existing Classification Logic
Implemented in `TrafficClassifier.classify` (`app/pipeline/classifier.py`):
- Thresholds:
  - If no telemetry: `unknown`
  - If $\text{risk\_score} \ge 0.80$: `malicious`
  - If $\text{risk\_score} \ge 0.50$: `suspicious`
  - Else: `legitimate`
- Explainability Signals:
  - Burst tags: `extreme_burst_rate`, `high_burst_rate`, `elevated_traffic_burst`
  - IP concentration tags: `critical_ip_concentration`, `client_ip_concentration`
  - UA anomaly tags: `critical_bot_ua_signature`, `non_standard_user_agent`
  - Error rate tags: `high_error_rate`, `elevated_error_rate`
  - Endpoint tags: `single_endpoint_flood`
  - Clean profile tags: `legitimate_traffic_profile`, `organic_demand_surge`

---

## 7. Existing Legitimate-RPS Logic
Implemented in `TrafficScorer`:
$$\text{suspicious\_fraction} = \max(\text{risk\_score}, 0.60 \times \text{ip\_concentration} + 0.40 \times \text{ua\_anomaly\_ratio})$$
- If $\text{risk\_score} < 0.20$, $\text{suspicious\_fraction} = 0.0$.
- Invariant strictly maintained:
  $$\text{suspicious\_rps} = \text{round}(\text{total\_rps} \times \text{suspicious\_fraction}, 2)$$
  $$\text{legitimate\_rps} = \text{round}(\text{total\_rps} - \text{suspicious\_rps}, 2)$$
  $$\text{legitimate\_rps} + \text{suspicious\_rps} == \text{total\_rps}$$

---

## 8. Existing API & Contract Behavior
- Endpoints:
  - `GET /health` -> `{"status": "ok", "service": "traffic-intelligence"}`
  - `GET /ready` -> `{"status": "ready", "service": "traffic-intelligence"}`
  - `GET /version` -> `{"service": "traffic-intelligence", "service_version": "0.1.0", "contract_version": "1.0.0", "model_version": "traffic-rules-v1", "environment": "development"}`
  - `POST /api/v1/traffic/assess` -> Canonical `TrafficAssessment` payload.
- Contract Conformance:
  - Validated against `contracts/traffic/traffic_assessment.schema.json`.
  - Strict Pydantic model (`extra="forbid"` on `TrafficAssessment`).

---

## 9. Baseline Test Results
Run command:
```powershell
python -m pytest services/traffic-intelligence/tests -v -o pythonpath=services/traffic-intelligence
```
**Recorded Result**: 18 passed in 1.00s.

Full microservices test suite:
```powershell
python run_tests.py
```
**Recorded Result**:
- Demo API: 9 passed
- Traffic Intelligence: 18 passed
- Demand Intelligence: 5 passed
- Platform & Decision Engine: 11 passed
- **All 4 service test suites passed (43 passed)**.

---

## 10. Existing Deterministic Scenarios
The repository already defines 6 deterministic evaluation scenarios in `services/traffic-intelligence/tests/test_scenarios.py`:
- `Scenario 1`: Normal legitimate traffic (baseline steady state)
- `Scenario 2`: Sudden legitimate spike (flash crowd / promo surge)
- `Scenario 3`: Suspicious burst traffic (elevated error rates, moderate concentration)
- `Scenario 4`: Highly concentrated suspicious traffic (L7 flood, credential stuffing, scrapers)
- `Scenario 5`: Mixed legitimate and suspicious traffic
- `Scenario 6`: Insufficient or unknown evidence

---

## 11. What is Already Complete
- [x] Deterministic heuristic pipeline architecture (`app/pipeline/`).
- [x] Feature extraction from raw telemetry (`FeatureExtractor`).
- [x] Multi-level burst and surge detector (`BurstDetector`).
- [x] Risk, legitimacy, and confidence scoring (`TrafficScorer`).
- [x] Clean partitioning into legitimate vs suspicious RPS.
- [x] Categorical classification and explainability signal generation (`TrafficClassifier`).
- [x] Strict contract adherence to `traffic_assessment.schema.json`.
- [x] Backward-compatible API endpoint with trace ID header propagation.
- [x] 18 automated tests across unit, contract, API, and scenario domains.

---

## 12. What is Missing from M1-1 through M1-3
- [ ] **M1-1**: Formal feature specification documentation in `docs/TRAFFIC_INTELLIGENCE_SPEC.md` documenting currently available vs not currently available features.
- [ ] **M1-2**: Reproducible experiment dataset generator script producing labeled feature vectors (`LEGITIMATE`, `MALICIOUS`, `MIXED`) from parameterized scenarios without saving giant CSV files to git.
- [ ] **M1-3**: Quantitative baseline benchmark report in `docs/TRAFFIC_MODEL_BASELINE.md` evaluating the heuristic model on the reproducible dataset (precision, recall, F1, FPR, FNR, latency, throughput, confidence distribution).

---

## 13. Recommended Next Steps
1. Execute Phase M1-1: Create `docs/TRAFFIC_INTELLIGENCE_SPEC.md` documenting all volume, client, HTTP, and temporal features.
2. Execute Phase M1-2: Create a deterministic dataset generator script in `services/traffic-intelligence/tools/generate_dataset.py`.
3. Execute Phase M1-3: Create a benchmark runner in `services/traffic-intelligence/tools/benchmark.py` and produce `docs/TRAFFIC_MODEL_BASELINE.md`.

