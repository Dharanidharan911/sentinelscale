# SentinelScale Member 1 — Traffic Intelligence: Implementation Context

> **Canonical persistent context for future AI coding agents.**
> Read this document in full before making any changes to `services/traffic-intelligence/`.
> Last updated: 2026-09-06 — Phase M1-4 complete.

---

## 1. Project Identity

**Project**: SentinelScale — Security-Aware Resource Intelligence for Cloud APIs
**Service**: Traffic Intelligence (Member 1 ownership)
**Repository**: https://github.com/Dharanidharan911/sentinelscale
**Branch**: `member1/traffic-intelligence`
**Service root**: `services/traffic-intelligence/`

---

## 2. Ownership Boundaries

Member 1 owns ONLY:
- `services/traffic-intelligence/**`
- `services/traffic-intelligence/tests/**`
- `services/traffic-intelligence/tools/**`
- `docs/TRAFFIC_*.md`
- `docs/M1_*.md`
- `docs/ai/traffic-intelligence-context.md`
- `docs/ai/MEMBER1_IMPLEMENTATION_CONTEXT.md` (this file)

DO NOT MODIFY:
- `services/demand-intelligence/**`
- `services/platform/**`
- `demo-api/**`
- `gateway/**`
- `infrastructure/**`
- Grafana / Docker Compose / HPA / PolicyGuardrail / DecisionEngine
- `contracts/traffic/traffic_assessment.schema.json` (FROZEN — shared integration contract)

---

## 3. Frozen Contract

The integration contract is frozen at v1.0.0:

  contracts/traffic/traffic_assessment.schema.json

This file MUST NOT be modified. It has `"additionalProperties": false`. Any new data from ML must flow through existing fields only (`top_signals[]`, `model_version`, etc.).

TrafficAssessment Pydantic model: `services/traffic-intelligence/app/models/traffic.py`
It uses `model_config = {"extra": "forbid"}` — strict validation.

---

## 4. Completed Phases

| Phase | Commit | Description |
|-------|--------|-------------|
| M1-0 | 4d5d67a | Baseline audit: `docs/M1_BASELINE_AUDIT.md` |
| M1-1 | 1b451b4 | Feature spec: `docs/TRAFFIC_INTELLIGENCE_SPEC.md` |
| M1-2 | ab1358e | Dataset generator: `tools/generate_dataset.py` |
| M1-3 | 608c427 | Heuristic benchmark: `docs/TRAFFIC_MODEL_BASELINE.md`, `tools/benchmark.py` |
| M1-4 | (see commit after 608c427) | Isolation Forest hybrid: `app/pipeline/ml_detector.py`, `tools/train_isolation_forest.py` |

---

## 5. Architecture Overview

`
AssessmentRequest (POST /api/v1/traffic/assess)
    |
    v
TrafficIntelligenceEngine (app/pipeline/engine.py)
    |
    |---> FeatureExtractor.extract() -> ExtractedTrafficFeatures (dataclass)
    |
    |---> BurstDetector.detect() -> BurstResult
    |
    |---> TrafficScorer.calculate_scores() -> ScoreResult  [heuristic]
    |
    |---> IsolationForestAnomalyDetector.detect() -> MLAnomalyResult  [ML]
    |
    |---> Hybrid aggregation (in engine.py)
    |
    +---> TrafficClassifier.classify() -> ClassificationResult
              |
              v
         TrafficAssessment (schema v1.0.0)
`

---

## 6. Key Files

| File | Role |
|------|------|
| `app/main.py` | FastAPI application, 50 lines |
| `app/config/settings.py` | All tunable settings (Pydantic BaseSettings) |
| `app/models/traffic.py` | Pydantic models: TrafficAssessment, AssessmentRequest, TrafficTelemetryInput |
| `app/pipeline/features.py` | ExtractedTrafficFeatures dataclass, FeatureExtractor.extract() |
| `app/pipeline/burst_detector.py` | BurstDetector.detect() - burst level classification |
| `app/pipeline/scorer.py` | TrafficScorer.calculate_scores() - weighted heuristic risk |
| `app/pipeline/classifier.py` | TrafficClassifier.classify() - label + top_signals |
| `app/pipeline/engine.py` | TrafficIntelligenceEngine - orchestrates full pipeline |
| `app/pipeline/ml_detector.py` | IsolationForestAnomalyDetector - IF inference + fallback |
| `app/models/weights/isolation_forest.joblib` | Trained model artifact (gitignored, 455 KB) |
| `tools/generate_dataset.py` | TrafficDatasetGenerator - 4 canonical scenarios |
| `tools/benchmark.py` | Heuristic vs Hybrid ML benchmark (--compare flag) |
| `tools/train_isolation_forest.py` | Trains IF on Scenarios A+B, evaluates on A/B/C/D |
| `tests/test_contract_conformance.py` | JSON schema validation against frozen contract |
| `tests/test_scenarios.py` | 6 canonical scenario tests |
| `tests/test_ml_detector.py` | 3 ML tests: inference, fallback, hybrid flow |

---

## 7. 7-D Feature Vector (CANONICAL ORDERING)

The following ordering is used in BOTH training (train_isolation_forest.py) and inference (ml_detector.py). It MUST NOT change unless both are updated simultaneously and the model is retrained.

`python
[total_rps, burst_ratio, error_rate, ip_concentration, ua_anomaly_ratio, single_endpoint_ratio, data_completeness]
`

Index 0: total_rps              - requests per second
Index 1: burst_ratio            - total_rps / baseline_rps
Index 2: error_rate             - status_5xx / total_requests (approx)
Index 3: ip_concentration       - top_ip_ratio (fraction of traffic from top IP)
Index 4: ua_anomaly_ratio       - non_standard_ua_ratio
Index 5: single_endpoint_ratio  - fraction hitting single endpoint
Index 6: data_completeness      - 1.0 if full telemetry, else derived

---

## 8. Hybrid Scoring Logic (engine.py)

`python
hybrid_risk = (1 - ML_ANOMALY_WEIGHT) * heuristic_risk + ML_ANOMALY_WEIGHT * anomaly_score
`

Flash crowd protection guard (bypasses ML weight):
`python
if heuristic_risk < 0.20 and ip_concentration < 0.15 and ua_anomaly_ratio < 0.05:
    hybrid_risk = heuristic_risk  # do not inflate
`

ML is only applied when:
1. settings.ENABLE_ML_ANOMALY_DETECTOR is True (default: True)
2. features.has_telemetry is True (telemetry was explicitly provided)
3. Model was loaded successfully (is_loaded = True)

---

## 9. ML Anomaly Score Normalization

Raw IsolationForest decision_function -> normalized anomaly score:
`python
normalized_normal = max(0.0, min(1.0, (raw_score + 0.20) / 0.40))
anomaly_score = round(1.0 - normalized_normal, 3)
is_anomaly = (pred == -1) OR (anomaly_score >= 0.60)
`

When is_anomaly=True, signal_tag="ml_anomaly_detected" is injected into top_signals[].

---

## 10. Model Artifact

Path: `services/traffic-intelligence/app/models/weights/isolation_forest.joblib`
Size: ~455 KB (455,965 bytes as of M1-4)
Format: joblib compress=3
Gitignored: YES (*.joblib in .gitignore)

To regenerate after cloning:
`
python services/traffic-intelligence/tools/train_isolation_forest.py --samples-per-scenario 500 --seed 42 --n-estimators 100 --contamination 0.02
`

The weights/ directory is tracked via `app/models/weights/.gitkeep`.

---

## 11. Settings (app/config/settings.py)

| Setting | Default | Purpose |
|---------|---------|---------|
| SERVICE_VERSION | 0.1.0 | API version |
| CONTRACT_VERSION | 1.0.0 | TrafficAssessment schema version |
| MODEL_VERSION | traffic-hybrid-v1 | Reported in every assessment |
| ENABLE_ML_ANOMALY_DETECTOR | True | Toggle ML on/off |
| ML_ANOMALY_WEIGHT | 0.30 | Weight of ML score in hybrid formula |
| BURST_RATIO_ELEVATED | 1.75 | Burst threshold |
| BURST_RATIO_SPIKE | 2.5 | Burst threshold |
| BURST_RATIO_EXTREME | 4.0 | Burst threshold |
| RISK_THRESHOLD_SUSPICIOUS | 0.50 | Classification threshold |
| RISK_THRESHOLD_MALICIOUS | 0.80 | Classification threshold |

---

## 12. Four Canonical Traffic Scenarios

| ID | Name | Expected Classification | Heuristic Result |
|----|------|-------------------------|-----------------|
| A | Steady Legitimate | LEGITIMATE | risk < 0.20 |
| B | Legitimate Flash Crowd | SUSPICIOUS or LEGITIMATE | moderate risk |
| C | Hostile L7 Attack | MALICIOUS | risk > 0.80 |
| D | Mixed Traffic | SUSPICIOUS or MALICIOUS | moderate-high risk |

---

## 13. Test Suite

Run from the repo root:
`
="C:\SentinelScale\services\traffic-intelligence"
python -m pytest services/traffic-intelligence/tests -v
`

Full cross-service suite:
`
python run_tests.py
`

Test files in `services/traffic-intelligence/tests/`:
- test_health.py (3 tests)
- test_traffic_api.py (4 tests)
- test_pipeline.py (4 tests)
- test_scenarios.py (6 tests)
- test_contract_conformance.py (1 test)
- test_benchmark.py (1 test)
- test_ml_detector.py (3 tests)

Total M1 tests: 22 unit + 2 integration = 24 tests as of M1-4.

---

## 14. Benchmark Results (M1-4)

| Mode | Mean Latency | P99 | Throughput | F1 |
|------|-------------|-----|------------|----|
| Heuristic (traffic-rules-v1) | 0.0192 ms | 0.0259 ms | 52,118 rps | 100% |
| Hybrid ML (traffic-hybrid-v1) | 5.5094 ms | 12.50 ms | 181.5 rps | 100% |

ML is ~286x slower due to sklearn overhead (numpy array allocation + tree traversal).

---

## 15. ML Model Performance (M1-4)

Confusion matrix on 100-sample test split (seed=1041):

| Scenario | True Class | Inliers | Outliers | Notes |
|----------|-----------|---------|----------|-------|
| A | Legitimate | 100 | 0 | Perfect |
| B | Legitimate | 89 | 11 | 11% false positive |
| C | Malicious | 0 | 100 | Perfect detection |
| D | Malicious | 0 | 100 | Perfect detection |

Flash crowd protection guard prevents Scenario B false positives from inflating risk.

---

## 16. Fallback Safety

IsolationForestAnomalyDetector NEVER raises an exception to the pipeline.
If the model is missing/corrupt/fails at inference: returns MLAnomalyResult(is_available=False).
Engine.py treats is_available=False as heuristic-only mode — the pipeline continues normally.

---

## 17. API Endpoints

All served on port 8001 (configurable via settings.PORT):

| Endpoint | Method | Description |
|----------|--------|-------------|
| /health | GET | Liveness check |
| /ready | GET | Readiness check |
| /version | GET | Service version |
| /api/v1/traffic/assess | POST | Main assessment endpoint |

---

## 18. Dependencies (requirements.txt as of M1-4)

Key additions in M1-4:
- scikit-learn>=1.4.0,<2.0.0
- joblib>=1.3.0,<2.0.0
- numpy>=1.26.0,<3.0.0

Installed versions at time of M1-4:
- scikit-learn==1.7.2
- joblib==1.5.2
- numpy==2.3.5

---

## 19. Git Commit History

`
608c427  test(m1): benchmark heuristic traffic intelligence     <- M1-3
ab1358e  feat(m1): add reproducible traffic dataset generator   <- M1-2
1b451b4  docs(m1): specify traffic feature vector               <- M1-1
4d5d67a  docs(m1): document traffic intelligence baseline audit <- M1-0
e46fe79  feat(traffic-intelligence): complete phase 1           <- baseline
`

M1-4 commit: `feat(m1): integrate isolation forest hybrid traffic intelligence`

---

## 20. Gitignore Notes

These files will NOT be committed (gitignored):
- `*.joblib` — model weights
- `__pycache__/`
- `.env`
- `*.pyc`

The `services/traffic-intelligence/app/models/weights/` directory is tracked via `.gitkeep`.

---

## 21. Known Issues / Design Decisions

1. **Training/inference feature ordering**: Both `train_isolation_forest.py` and `ml_detector.py` use identical inline feature ordering. The training script uses raw attribute access from TelemetryInput objects (not FeatureExtractor.extract()) for speed; the ordering is cross-checked and matches.

2. **Scenario B false positives**: 11% of flash-crowd samples are flagged by IF alone. This is intentional — the hybrid engine's guard prevents risk inflation for legitimately low-risk flash crowds.

3. **No incremental training**: The IF model is retrained from scratch via train_isolation_forest.py. Online learning is not implemented (future M1-11 drift detection).

4. **Model loaded once at startup**: `IsolationForestAnomalyDetector` is instantiated in `TrafficIntelligenceEngine.__init__()`. Model is not reloaded per-request. To reload: restart the service.

5. **Contamination=0.02**: This means 2% of training data is assumed anomalous. Since we train on legitimate-only data, this small contamination factor prevents overfitting to perfect normality.

---

## 22. What NOT to Implement Until Approved

The following phases are NOT yet implemented. Do NOT begin them without explicit user approval:

- M1-5: Real telemetry ingestion (REST endpoint)
- M1-6: Sliding window burst detector
- M1-7: Composite risk weighting
- M1-8: Confidence calibration
- M1-9: SHAP explainability
- M1-10: Multi-model ensemble
- M1-11: Drift detection
- M1-12: MLflow lifecycle management
- M1-13: Prometheus metrics exporter

---

## 23. Startup Instructions

Run service locally:
`
cd services/traffic-intelligence
pip install -r requirements.txt
uvicorn app.main:app --port 8001 --reload
`

If model weights are missing, retrain first:
`
python tools/train_isolation_forest.py --samples-per-scenario 500 --seed 42
`

The service will start in heuristic-only mode even if weights are missing (safe fallback).

---

## Revision History

| Date | Agent | Phase | Changes |
|------|-------|-------|---------|
| 2026-09-03 | Antigravity (initial) | M1-0 to M1-3 | Baseline audit, spec, dataset generator, benchmark |
| 2026-09-05 | Antigravity (continuation) | M1-4 | Isolation Forest hybrid integration |
| 2026-09-06 | Antigravity (continuation) | M1-4 finalization | Docs, tests verified, committed |
