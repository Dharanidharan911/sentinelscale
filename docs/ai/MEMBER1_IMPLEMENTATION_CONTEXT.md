# SentinelScale Member 1 — Traffic Intelligence: Implementation Context

> **Canonical persistent context for future AI coding agents.**
> Read this document in full before making any changes to `services/traffic-intelligence/`.
> Last updated: 2026-09-06 — Phase M1-4 + M1-4 Hardening complete (committed checkpoint).

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

  `contracts/traffic/traffic_assessment.schema.json`

This file MUST NOT be modified. It has `"additionalProperties": false`. Any new data from ML
must flow through existing fields only (`top_signals[]`, `model_version`, etc.).

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
| M1-4 | 98f8d7b | Isolation Forest hybrid: `app/pipeline/ml_detector.py`, `tools/train_isolation_forest.py` |
| M1-4H | see Section 19 | Hardening: normalization fix, latency optimization, canonical training path, weight tests |

---

## 5. Architecture Overview

```
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
```

---

## 6. Key Files

| File | Role |
|------|------|
| `app/main.py` | FastAPI application |
| `app/config/settings.py` | All tunable settings (Pydantic BaseSettings) |
| `app/models/traffic.py` | Pydantic models: TrafficAssessment, AssessmentRequest, TrafficTelemetryInput |
| `app/pipeline/features.py` | ExtractedTrafficFeatures dataclass, FeatureExtractor.extract() |
| `app/pipeline/burst_detector.py` | BurstDetector.detect() - burst level classification |
| `app/pipeline/scorer.py` | TrafficScorer.calculate_scores() - weighted heuristic risk |
| `app/pipeline/classifier.py` | TrafficClassifier.classify() - label + top_signals |
| `app/pipeline/engine.py` | TrafficIntelligenceEngine - orchestrates full pipeline |
| `app/pipeline/ml_detector.py` | IsolationForestAnomalyDetector - IF inference + fallback |
| `app/models/weights/isolation_forest.joblib` | Trained model artifact (gitignored, ~455 KB) |
| `tools/generate_dataset.py` | TrafficDatasetGenerator - 4 canonical scenarios |
| `tools/benchmark.py` | Heuristic vs Hybrid ML benchmark (--compare flag) |
| `tools/train_isolation_forest.py` | Trains IF on Scenarios A+B, evaluates on A/B/C/D |
| `tests/test_contract_conformance.py` | JSON schema validation against frozen contract |
| `tests/test_scenarios.py` | 6 canonical scenario tests |
| `tests/test_ml_detector.py` | 10 ML tests: normalization, inference, fallback, weight-verification, hybrid-flow |

---

## 7. 7-D Feature Vector (CANONICAL ORDERING)

The following ordering is used in BOTH training (`train_isolation_forest.py`) and inference
(`ml_detector.py`). It MUST NOT change unless both are updated simultaneously and the model retrained.

```python
[total_rps, burst_ratio, error_rate, ip_concentration, ua_anomaly_ratio, single_endpoint_ratio, data_completeness]
```

| Index | Feature | Unit | Normalization |
|-------|---------|------|---------------|
| 0 | `total_rps` | req/sec | Divided by `TOTAL_RPS_SCALE = 2000.0` → [0, ~1] |
| 1 | `burst_ratio` | ratio | Raw (typically 0.5–15+) |
| 2 | `error_rate` | ratio | Raw [0, 1] |
| 3 | `ip_concentration` | ratio | Raw [0, 1] |
| 4 | `ua_anomaly_ratio` | ratio | Raw [0, 1] |
| 5 | `single_endpoint_ratio` | ratio | Raw [0, 1] |
| 6 | `data_completeness` | ratio | Raw [0, 1] |

**IMPORTANT (M1-4H fix)**: `total_rps` is divided by `TOTAL_RPS_SCALE = 2000.0` (defined in
`ml_detector.py`, imported by `train_isolation_forest.py`). The same constant MUST be used
in both training and inference. This was added in M1-4H to fix scale mismatch where
`total_rps` (35–1336 range) dominated the IF distance metric relative to ratio features [0,1].

The single canonical normalization function is `IsolationForestAnomalyDetector.normalize_features()`.
Training applies the same formula in `extract_feature_matrix()` by importing `TOTAL_RPS_SCALE`.

**IMPORTANT**: `has_telemetry` is a field in `ExtractedTrafficFeatures` but is NOT part of the
7-D ML feature vector. When `asdict(features)` is called in `engine.py`, the key is present in
the dict but `normalize_features()` only reads the 7 canonical keys via `.get()` — safe.

---

## 8. Hybrid Scoring Logic (engine.py)

```python
hybrid_risk = (1 - ML_ANOMALY_WEIGHT) * heuristic_risk + ML_ANOMALY_WEIGHT * anomaly_score
```

Flash crowd protection guard (bypasses ML weight — prevents false risk elevation for legitimate bursts):
```python
if heuristic_risk < 0.20 and ip_concentration < 0.15 and ua_anomaly_ratio < 0.05:
    hybrid_risk = heuristic_risk  # do not inflate
```

ML is only applied when:
1. `settings.ENABLE_ML_ANOMALY_DETECTOR` is True (default: True)
2. `features.has_telemetry` is True (telemetry was explicitly provided)
3. Model was loaded successfully (`is_loaded = True`)

---

## 9. ML Anomaly Score Normalization

Raw IsolationForest `decision_function` → normalized anomaly score:
```python
normalized_normal = max(0.0, min(1.0, (raw_score + 0.20) / 0.40))
anomaly_score = round(1.0 - normalized_normal, 3)
# raw_score ~ +0.20 -> very normal -> anomaly_score ~ 0.0
# raw_score ~ -0.20 -> highly anomalous -> anomaly_score ~ 1.0

pred = 1 if raw_score >= 0.0 else -1   # derived from decision_function sign (NO separate predict() call)
is_anomaly = (pred == -1) OR (anomaly_score >= 0.60)
```

When `is_anomaly=True`, `signal_tag="ml_anomaly_detected"` is injected into `top_signals[]`.

**IMPORTANT (M1-4H)**: `predict()` is NOT called. `pred` is derived from `sign(decision_function())`.
IsolationForest's `predict()` is internally equivalent to this at threshold=0. This eliminates
a second full 100-tree traversal (~2.7 ms saved per call).

---

## 10. Model Artifact

Path: `services/traffic-intelligence/app/models/weights/isolation_forest.joblib`
Size: ~455 KB
Format: joblib `compress=3`
Gitignored: YES (`*.joblib` in `.gitignore`)

To regenerate after cloning (deterministic, seed=42):
```bash
python services/traffic-intelligence/tools/train_isolation_forest.py \
  --samples-per-scenario 500 --seed 42 --n-estimators 100 --contamination 0.02
```

The `weights/` directory is tracked via `app/models/weights/.gitkeep`.

**M1-4H**: Model was retrained after normalization fix. The new model applies
`total_rps / TOTAL_RPS_SCALE` normalization during training via `extract_feature_matrix()`.

---

## 11. Settings (app/config/settings.py)

| Setting | Default | Purpose |
|---------|---------|---------| 
| `SERVICE_VERSION` | `0.1.0` | API version |
| `CONTRACT_VERSION` | `1.0.0` | TrafficAssessment schema version |
| `MODEL_VERSION` | `traffic-hybrid-v1` | Reported in every assessment |
| `ENABLE_ML_ANOMALY_DETECTOR` | `True` | Toggle ML on/off |
| `ML_ANOMALY_WEIGHT` | `0.30` | Weight of ML score in hybrid formula |
| `BURST_RATIO_ELEVATED` | `1.75` | Burst threshold |
| `BURST_RATIO_SPIKE` | `2.5` | Burst threshold |
| `BURST_RATIO_EXTREME` | `4.0` | Burst threshold |
| `RISK_THRESHOLD_SUSPICIOUS` | `0.50` | Classification threshold |
| `RISK_THRESHOLD_MALICIOUS` | `0.80` | Classification threshold |

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
```powershell
$env:PYTHONPATH="$PWD\services\traffic-intelligence"
python -m pytest services/traffic-intelligence/tests -v
```

Full cross-service suite:
```
python run_tests.py
```

Test files in `services/traffic-intelligence/tests/`:

| File | Tests | Coverage |
|------|-------|---------|
| `test_health.py` | 3 | Health/ready/version endpoints |
| `test_traffic_api.py` | 4 | API request/response |
| `test_pipeline.py` | 4 | Feature extractor, burst detector, scorer |
| `test_scenarios.py` | 6 | 6 canonical deterministic scenarios |
| `test_contract_conformance.py` | 1 | JSON schema validation |
| `test_benchmark.py` | 3 | Dataset determinism, labels, benchmark execution |
| `test_ml_detector.py` | 10 | Normalization, inference, fallback (missing+malformed), weight-verification (3 tests), hybrid flow |

**Total M1 tests: 31** (as of M1-4H committed checkpoint)

---

## 14. Benchmark Results

### Pre-Hardening (M1-4 original, committed at 98f8d7b)

| Mode | Mean Latency | P99 | Throughput | F1 |
|------|-------------|-----|------------|-----|
| Heuristic (`traffic-rules-v1`) | 0.0192 ms | 0.0259 ms | 52,118 rps | 100% |
| Hybrid ML (`traffic-hybrid-v1`) | 7.50 ms | 14.7 ms | 133 rps | 100% |

### Post-Hardening (M1-4H, measured at commit, 250 samples/scenario, seed=42)

| Mode | Mean Latency | P50 | P95 | P99 | Throughput | Precision | Recall | F1 |
|------|-------------|-----|-----|-----|------------|-----------|--------|----|
| Heuristic (`traffic-rules-v1`) | 0.0237 ms | 0.0198 ms | 0.042 ms | 0.089 ms | 42,244 rps | 100% | 100% | 100% |
| Hybrid ML (`traffic-hybrid-v1`) | 2.4011 ms | 2.1898 ms | 3.5331 ms | 3.9568 ms | 417 rps | 100% | 100% | 100% |

**M1-4H latency improvement**: 68% reduction (7.50 ms → 2.40 ms mean); 3× throughput increase.

**Why hybrid is still slower than heuristic**: The residual ~2.4 ms is inherent sklearn
IsolationForest tree-traversal cost (100 trees). Every practical optimization has been applied
(see Section 21, item 4). Further reduction would require fewer estimators or a different algorithm.

---

## 15. ML Model Performance (post M1-4H hardening, seed=42+999)

Confusion matrix on 100-sample test split (after retraining with `total_rps` normalization):

| Scenario | True Class | Inliers | Outliers | Notes |
|----------|-----------|---------|----------|-------|
| A | Legitimate | 100 | 0 | 0% false positive |
| B | Legitimate | 87 | 13 | 13% false positive — guarded by flash-crowd protection |
| C | Malicious | 0 | 100 | 100% detection |
| D | Malicious | 0 | 100 | 100% detection |

**Honest accuracy statement**: Both heuristic and hybrid achieve F1=100% on the 4-scenario
synthetic benchmark. ML adds no accuracy improvement on synthetic data. The ML value is as an
additional continuous anomaly signal for ambiguous real-world patterns not covered by heuristic
thresholds. This is documented; not hidden.

---

## 16. Fallback Safety

`IsolationForestAnomalyDetector` NEVER raises an exception to the pipeline.

| Condition | Behavior |
|-----------|---------|
| `isolation_forest.joblib` missing | `MLAnomalyResult(is_available=False)` → heuristic-only |
| Model load error (corrupt file) | Same — warning logged |
| `ENABLE_ML_ANOMALY_DETECTOR=False` | ML branch skipped in `engine.py` |
| `has_telemetry=False` | ML branch skipped in `engine.py` |
| Runtime inference exception | Caught, logged, heuristic result used |
| Malformed/empty features dict | `.get()` defaults fill in zeros; safe result |

Engine.py treats `is_available=False` as heuristic-only mode — the pipeline continues normally.

---

## 17. API Endpoints

All served on port 8001 (configurable via `settings.PORT`):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness check |
| `/ready` | GET | Readiness check |
| `/version` | GET | Service version |
| `/api/v1/traffic/assess` | POST | Main assessment endpoint |

---

## 18. Dependencies (requirements.txt as of M1-4)

Key additions in M1-4:
- `scikit-learn>=1.4.0,<2.0.0`
- `joblib>=1.3.0,<2.0.0`
- `numpy>=1.26.0,<3.0.0`

Installed versions at time of M1-4H:
- `scikit-learn==1.7.2`
- `joblib==1.5.2`
- `numpy==2.3.5`

---

## 19. Git Commit History

```
98f8d7b  feat(m1): integrate isolation forest hybrid traffic intelligence   <- M1-4
608c427  test(m1): benchmark heuristic traffic intelligence                  <- M1-3
ab1358e  feat(m1): add reproducible traffic dataset generator               <- M1-2
1b451b4  docs(m1): specify traffic feature vector                           <- M1-1
4d5d67a  docs(m1): document traffic intelligence baseline audit             <- M1-0
e46fe79  feat(traffic-intelligence): complete phase 1                       <- baseline
```

M1-4H hardening commit: committed in this session (after 98f8d7b).

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

1. **Single canonical feature extraction path**: Both `train_isolation_forest.py` and
   `ml_detector.py` use `FeatureExtractor.extract()` → `asdict()` as the canonical
   feature path (fixed in M1-4H; previously training used inline dict construction).

2. **`total_rps` normalization (M1-4H fix)**: `total_rps` is divided by `TOTAL_RPS_SCALE = 2000.0`
   at both training and inference time. This constant is defined in `ml_detector.py` and
   imported by `train_isolation_forest.py`. Changing it requires retraining the model.
   _Old state (M1-4)_: `total_rps` was NOT normalized, causing scale mismatch with ratio features.

3. **Scenario B false positives (13%)**: 13% of legitimate flash-crowd samples are flagged as
   anomalies by the IF model alone. The hybrid engine flash-crowd protection guard prevents this
   from inflating the risk score for genuinely low-risk traffic.

4. **<1 ms latency target not fully achieved**: Post-hardening warm inference is ~2.4 ms mean
   (down from ~7.5 ms before). Residual cost is inherent sklearn IsolationForest tree traversal
   (100 trees). Optimizations applied: eliminated redundant `predict()` call; `n_jobs=1` forced;
   warm-up inference at model load; pre-allocated numpy buffer. Further reduction requires fewer
   estimators (accuracy trade-off) or a different algorithm — out of M1-4 scope.

5. **`predict()` is NOT called separately**: `pred` is derived from `sign(decision_function())`.
   IsolationForest's `predict()` is internally equivalent to this at offset=0. This avoids a
   second full tree traversal (~2.7 ms saved per call).

6. **Model loaded once at startup**: `IsolationForestAnomalyDetector` is instantiated in
   `TrafficIntelligenceEngine.__init__()`. Model is not reloaded per-request. To reload: restart.

7. **No incremental training**: IF model retrained from scratch via `train_isolation_forest.py`.
   Online learning not implemented (future M1-11 drift detection, if ever specified).

8. **Contamination=0.02**: 2% of training data assumed anomalous. Since training uses legitimate-
   only traffic, this small factor prevents over-fitting to perfect normality.

9. **ML adds no accuracy improvement on current synthetic benchmark**: Both heuristic and hybrid
   achieve F1=100% on the 4-scenario synthetic dataset. This is honest and documented.

10. **Pre-allocated numpy buffer is NOT thread-safe**: `self._buf` is reused in-place each call.
    Safe in current single-worker FastAPI/uvicorn deployment. If multi-threaded deployment is
    introduced, make `_buf` a local variable in `detect()` instead.

---

## 22. What NOT to Implement Without Explicit Specification

The following phases are named but have NO repository-defined requirements, specs, or test contracts.
Do NOT implement them without explicit written requirements from the project owner:

- M1-5: Real telemetry ingestion (REST endpoint)
- M1-6: Sliding window burst detector
- M1-7: Composite risk weighting
- M1-8: Confidence calibration
- M1-9: SHAP explainability
- M1-10: Multi-model ensemble
- M1-11: Drift detection
- M1-12: MLflow lifecycle management
- M1-13: Prometheus metrics exporter

**These are DEFERRED. The repository contains no specifications for them.**

---

## 23. Startup Instructions

Run service locally:
```bash
cd services/traffic-intelligence
pip install -r requirements.txt
uvicorn app.main:app --port 8001 --reload
```

If model weights are missing, retrain first:
```bash
python tools/train_isolation_forest.py --samples-per-scenario 500 --seed 42
```

The service will start in heuristic-only mode even if weights are missing (safe fallback).

---

## 24. Next-Agent Instructions

**Branch**: `member1/traffic-intelligence`
**Last stable commit**: M1-4H hardening (committed in this session, pushed to remote)
**Status**: Member 1 is COMPLETE through M1-4H. All defined phases (M1-0 through M1-4H) are done.

**Before making any changes**:
1. Read this file in full.
2. Read `docs/ai/traffic-intelligence-context.md`.
3. Run `python -m pytest services/traffic-intelligence/tests -v` and confirm 31/31 pass.
4. Run `python run_tests.py` and confirm all 4 service suites pass.

**Critical rules**:
- `contracts/traffic/traffic_assessment.schema.json` is FROZEN — do not modify.
- Do not import from `services/demand-intelligence/` or `services/platform/`.
- The model artifact (`isolation_forest.joblib`) is gitignored — regenerate if missing.
- M1-5 through M1-13 have NO specifications — do not implement without explicit requirements.
- All 31 M1 tests must pass before any commit.
- Feature vector ordering and `TOTAL_RPS_SCALE` must stay consistent between training and inference.

**Gap analysis (as of M1-4H)**:

| Phase | Status | Notes |
|-------|--------|-------|
| M1-0 | COMPLETE | Baseline audit |
| M1-1 | COMPLETE | Feature specification |
| M1-2 | COMPLETE | Dataset generator |
| M1-3 | COMPLETE | Heuristic benchmark |
| M1-4 | COMPLETE | Isolation Forest hybrid |
| M1-4H | COMPLETE | Normalization, latency hardening, canonical training path |
| M1-5+ | DEFERRED | No specs defined in repository |

---

## Revision History

| Date | Agent | Phase | Changes |
|------|-------|-------|---------|
| 2026-09-03 | Antigravity (initial) | M1-0 to M1-3 | Baseline audit, spec, dataset generator, benchmark |
| 2026-09-05 | Antigravity (continuation) | M1-4 | Isolation Forest hybrid integration |
| 2026-09-06 | Antigravity (continuation) | M1-4 finalization | Docs, tests verified, committed at 98f8d7b |
| 2026-09-06 | Antigravity (hardening) | M1-4H | Normalization fix (TOTAL_RPS_SCALE), predict() elimination, n_jobs=1, warm-up, canonical training path, 7 new tests, retrain, clean commit checkpoint |
