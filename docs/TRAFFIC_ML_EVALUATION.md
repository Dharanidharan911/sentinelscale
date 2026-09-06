# Traffic Intelligence — ML Evaluation Report

**Phase**: M1-4 Hardening — Isolation Forest Hybrid Integration
**Date**: 2026-09-06
**Branch**: `member1/traffic-intelligence`
**Model**: `IsolationForest` (scikit-learn 1.7.2, n_estimators=100, contamination=0.02, n_jobs=1)

---

## 1. Model Architecture

The M1-4 hybrid intelligence pipeline combines deterministic heuristic rules with an
unsupervised Isolation Forest anomaly detector.

```
AssessmentRequest
    |
    v
FeatureExtractor.extract()    -> ExtractedTrafficFeatures (dataclass)
    |
    |---> BurstDetector.detect()    -> burst signal
    |
    |---> TrafficScorer.calculate_scores()   -> heuristic risk/legitimacy/confidence
    |
    |---> IsolationForestAnomalyDetector.detect()  -> ML anomaly score [0,1]
              |
              v
         Hybrid Aggregation (engine.py)
              |
              v
         TrafficClassifier.classify() -> TrafficAssessment v1.0.0
```

### 7-D Feature Vector (canonical ordering)

| Index | Feature | Source | Scale |
|-------|---------|--------|-------|
| 0 | `total_rps` | `telemetry.total_rps / TOTAL_RPS_SCALE` | [0, ~1] after normalization |
| 1 | `burst_ratio` | `total_rps / baseline_rps` | [0.5, 15+] |
| 2 | `error_rate` | `(4xx + 5xx) / total_requests` | [0, 1] |
| 3 | `ip_concentration` | `telemetry.top_ip_ratio` | [0, 1] |
| 4 | `ua_anomaly_ratio` | `telemetry.non_standard_ua_ratio` | [0, 1] |
| 5 | `single_endpoint_ratio` | `telemetry.single_endpoint_ratio` | [0, 1] |
| 6 | `data_completeness` | derived (fraction of optional fields present) | [0, 1] |

`TOTAL_RPS_SCALE = 2000.0` is a deterministic constant defined in `ml_detector.py`
and imported by `train_isolation_forest.py`. The same value is applied at both
training time and inference time.

---

## 2. Training Setup

| Parameter | Value |
|-----------|-------|
| Training algorithm | `IsolationForest` (sklearn) |
| n_estimators | 100 |
| max_samples | `auto` |
| contamination | 0.02 |
| random_state / seed | 42 |
| n_jobs (training) | 1 |
| Training scenarios | A (Steady Legitimate) + B (Legitimate Flash Crowd) |
| Training samples | 500 per scenario x 2 = 1000 total |
| Feature extraction | `FeatureExtractor.extract()` (canonical path, same as inference) |
| Test scenarios | A, B, C (Hostile L7), D (Mixed) -- 100 each |

**Rationale**: Training on legitimate-only traffic teaches the IF what normality
looks like. Anomalies (C/D) are never shown; the model generalises from structure.

### Training command (reproducible, seed=42)

`
python services/traffic-intelligence/tools/train_isolation_forest.py \
  --samples-per-scenario 500 --seed 42 --n-estimators 100 --contamination 0.02
`

> **Note**: `isolation_forest.joblib` is gitignored (`*.joblib`). Re-run the above
> command to regenerate it after cloning. The weights/ directory is tracked via `.gitkeep`.

---

## 3. Feature Consistency Verification (M1-4 Hardening)

**Issue found**: Training script previously used inline feature construction separate
from `FeatureExtractor.extract()`. Although numerically equivalent for the tested
samples, it was brittle (two divergent code paths).

**Fix**: `train_isolation_forest.py` now delegates entirely to `FeatureExtractor.extract()`
for all training samples. There is now exactly one feature extraction code path.

**Normalization issue found**: `total_rps` was NOT normalized before this hardening.
It ranged from ~35 RPS (Scenario A) to ~1336 RPS (Scenario C) while all other
features are ratios in [0, 1]. This scale mismatch meant total_rps dominated the
Isolation Forest distance metric.

**Fix**: `total_rps` is divided by `TOTAL_RPS_SCALE = 2000.0` (a deterministic
constant) at both training and inference time. `normalize_features()` in
`ml_detector.py` is the single transformation point.

---

## 4. Test Evaluation (100 samples per scenario, seed=42+999)

| Scenario | Description | Inliers | Outliers (Anomalies) | Notes |
|----------|-------------|---------|----------------------|-------|
| A | Steady Legitimate | 100 | 0 | Perfect, 0% false positive |
| B | Legitimate Flash Crowd | 87 | 13 | 13% false positive (see flash-crowd guard) |
| C | Hostile L7 Attack | 0 | 100 | 100% detected |
| D | Mixed Traffic | 0 | 100 | 100% detected |

Scenario B false positives are mitigated by the hybrid engine flash-crowd protection
guard which bypasses the ML weight when heuristic_risk < 0.20 AND ip_concentration
< 0.15 AND ua_anomaly_ratio < 0.05.

---

## 5. Performance Hardening (M1-4)

### Issues found in original implementation

| Issue | Impact |
|-------|--------|
| Double sklearn traversal: `decision_function()` + `predict()` called separately | ~5.5 ms per call; `predict()` is a full second tree traversal |
| `n_jobs=-1` on loaded model | Thread-dispatch overhead dominates single-sample latency (+1-3 ms) |
| No warm-up inference at model load | First real request pays cold-start penalty (~2.5 ms extra) |
| `total_rps` not normalized | Scale mismatch skewed IF distance metric |
| Two separate feature extraction paths | Training vs inference divergence risk |

### Fixes applied

| Fix | Mechanism |
|-----|-----------|
| Eliminate `predict()` call | Derive pred from sign of `decision_function()` (`score >= 0 -> inlier`) |
| Force `n_jobs=1` on loaded model | Set `model.n_jobs = 1` after joblib.load() |
| Warm-up inference at load | Run `model.decision_function(zeros)` in `_load_model()` |
| Normalize `total_rps` | `total_rps / TOTAL_RPS_SCALE` in both training and inference |
| Single feature extraction path | `train_isolation_forest.py` uses `FeatureExtractor.extract()` |
| Pre-allocated numpy buffer | `self._buf = np.zeros((1,7))` reused in-place each call |

---

## 6. Comparative Benchmark (250 samples per scenario, seed=42)

| Mode | Mean Latency | P99 Latency | Throughput | Precision | Recall | F1 |
|------|-------------|-------------|------------|-----------|--------|----|
| Heuristic only (traffic-rules-v1) | 0.0218 ms | 0.1161 ms | 45,848 rps | 100% | 100% | 100% |
| Hybrid ML (traffic-hybrid-v1) | 2.6031 ms | 7.1609 ms | 384 rps | 100% | 100% | 100% |

Before hardening (from original M1-4 commit):
- Hybrid mean: 7.50 ms / P99: 14.7 ms / throughput: 133 rps

**Improvement from hardening**: 65% latency reduction (7.50 ms -> 2.60 ms mean).

### ML detector isolated warm inference (1000 runs)

| Metric | Value |
|--------|-------|
| Mean | 2.6154 ms |
| P50 | 2.0667 ms |
| P95 | 5.4670 ms |
| P99 | 7.4688 ms |
| Min | 1.8694 ms |

The residual latency is inherent sklearn IsolationForest tree traversal cost
(100 trees, ~300-1000 samples per tree). Further reduction would require either
a shallower forest (fewer estimators, less accuracy) or a different algorithm
(e.g., compiled/Cython implementation -- out of scope for M1-4).

---

## 7. Honest Accuracy Statement

On the current synthetic benchmark, heuristic F1 = 100% and hybrid F1 = 100%.
**Both systems perfectly classify the canonical four scenarios.**

The synthetic scenarios are designed with clear separation between legitimate and
malicious feature distributions; a heuristic rule engine based on thresholds is
sufficient for perfect classification on this dataset.

The value of the ML component is NOT demonstrated by accuracy improvement on the
synthetic benchmark. Its role is:
1. Providing an additional evidence signal for ambiguous real-world traffic patterns
   that fall between heuristic thresholds.
2. Detecting novel attack patterns not covered by the explicit heuristic rules.
3. Producing a continuous anomaly score vs a threshold-based binary signal.

These properties are not measurable on the current synthetic benchmark and will be
evaluated with real telemetry in future phases (M1-5+).

---

## 8. Hybrid Scoring Formula

`
hybrid_risk = (1 - ML_ANOMALY_WEIGHT) * heuristic_risk + ML_ANOMALY_WEIGHT * anomaly_score
`

Default `ML_ANOMALY_WEIGHT = 0.30` (configurable via settings).

### Flash Crowd Protection Guard

If ALL of the following hold, ML weight is bypassed:
- `heuristic_risk < 0.20`
- `features.ip_concentration < 0.15`
- `features.ua_anomaly_ratio < 0.05`

### Anomaly Score Normalization

`
normalized_normal = max(0.0, min(1.0, (raw_score + 0.20) / 0.40))
anomaly_score = round(1.0 - normalized_normal, 3)
is_anomaly = (pred == -1) OR (anomaly_score >= 0.60)
`

`pred` is derived from `sign(decision_function)` -- no separate `predict()` call.

---

## 9. Contract Conformance

`TrafficAssessment v1.0.0` schema is FROZEN at `contracts/traffic/traffic_assessment.schema.json`.
ML signal appears only in `top_signals[]` field as `"ml_anomaly_detected"` string.

All 31 M1 tests: PASSED
All 4 service suites (`python run_tests.py`): PASSED
`contracts/traffic/traffic_assessment.schema.json`: UNCHANGED

---

## 10. Fallback Behaviour

| Condition | Behaviour |
|-----------|-----------|
| `isolation_forest.joblib` missing | Graceful fallback to heuristic-only; no crash |
| Model load error (corrupted file) | Warning logged; heuristic-only |
| `ENABLE_ML_ANOMALY_DETECTOR=false` | ML disabled at settings level |
| Telemetry absent (`has_telemetry=False`) | ML skipped; heuristic-only |
| Runtime inference exception | Exception caught, logged; heuristic result used |
| Malformed/empty features dict | Default values fill in; safe result returned |

---

## 11. Future Phases

| Phase | Task |
|-------|------|
| M1-5 | Real telemetry ingestion |
| M1-6 | Sliding window burst detector |
| M1-8 | Confidence calibration |
| M1-9 | SHAP explainability |
| M1-11 | Drift detection |
| M1-12 | MLflow lifecycle |
