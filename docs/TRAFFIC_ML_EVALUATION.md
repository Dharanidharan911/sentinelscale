# Traffic Intelligence — ML Evaluation Report

**Phase**: M1-4 — Isolation Forest Hybrid Integration
**Date**: 2026-09-06
**Branch**: `member1/traffic-intelligence`
**Model**: `IsolationForest` (scikit-learn 1.7.2, n_estimators=100, contamination=0.02)

---

## 1. Model Architecture

The M1-4 upgrade introduces a **hybrid intelligence pipeline** combining deterministic heuristic rules with an unsupervised Isolation Forest anomaly detector.

`
AssessmentRequest
    |
    v
FeatureExtractor         -> 7-D feature vector
    |
    |---> BurstDetector   -> burst signal
    |
    |---> TrafficScorer   -> heuristic risk / legitimacy / confidence
    |
    +---> IsolationForestAnomalyDetector  -> ML anomaly score [0.0-1.0]
              |
              v
         Hybrid Aggregation Engine
              |
              v
         TrafficClassifier -> TrafficAssessment v1.0.0
`

### 7-D Feature Vector (canonical ordering)

| Index | Feature | Source |
|-------|---------|--------|
| 0 | `total_rps` | `telemetry.total_rps` |
| 1 | `burst_ratio` | `total_rps / baseline_rps` |
| 2 | `error_rate` | `status_5xx / total_requests` |
| 3 | `ip_concentration` | `telemetry.top_ip_ratio` |
| 4 | `ua_anomaly_ratio` | `telemetry.non_standard_ua_ratio` |
| 5 | `single_endpoint_ratio` | `telemetry.single_endpoint_ratio` |
| 6 | `data_completeness` | derived; 1.0 = full telemetry present |

---

## 2. Training Setup

| Parameter | Value |
|-----------|-------|
| Training algorithm | `IsolationForest` (sklearn) |
| n_estimators | 100 |
| max_samples | `auto` |
| contamination | 0.02 |
| random_state / seed | 42 |
| n_jobs | -1 (all cores) |
| Training scenarios | A (Steady Legitimate) + B (Legitimate Flash Crowd) |
| Training samples | 500 per scenario x 2 = 1000 total |
| Test scenarios | A, B, C (Hostile L7), D (Mixed) - 100 each |

Training exclusively on legitimate traffic forces the Isolation Forest to learn normality. Anomalies are never shown during training.

### Training command (reproducible)

`
python services/traffic-intelligence/tools/train_isolation_forest.py --samples-per-scenario 500 --seed 42 --n-estimators 100 --contamination 0.02
`

> The model artifact (`isolation_forest.joblib`) is gitignored. Re-run the above command to regenerate after cloning.

---

## 3. Test Evaluation (100 samples per scenario, seed=42+999)

| Scenario | Description | Inliers | Outliers | Detection Rate |
|----------|-------------|---------|----------|----------------|
| A | Steady Legitimate | 100 | 0 | 0% false positive |
| B | Legitimate Flash Crowd | 89 | 11 | 11% false positive |
| C | Hostile L7 Attack | 0 | 100 | 100% detected |
| D | Mixed Traffic | 0 | 100 | 100% detected |

Scenario B: 11 flash-crowd samples flagged by IF alone. The hybrid engine flash-crowd protection guard prevents this from inflating the final risk score.

---

## 4. Hybrid Scoring Formula

`
hybrid_risk = (1 - ML_ANOMALY_WEIGHT) * heuristic_risk + ML_ANOMALY_WEIGHT * anomaly_score
`

Default ML_ANOMALY_WEIGHT = 0.30 (configurable).

### Flash Crowd Protection Guard

If ALL of the following hold, ML weight is bypassed (hybrid_risk = heuristic_risk):
- heuristic_risk < 0.20
- features.ip_concentration < 0.15
- features.ua_anomaly_ratio < 0.05

### Anomaly Score Normalization

`
normalized_normal = max(0.0, min(1.0, (raw_score + 0.20) / 0.40))
anomaly_score = round(1.0 - normalized_normal, 3)
is_anomaly = (pred == -1) OR (anomaly_score >= 0.60)
`

---

## 5. Comparative Benchmark (250 samples per scenario, seed=42)

| Mode | Mean Latency | P99 Latency | Throughput | Precision | Recall | F1 |
|------|-------------|-------------|------------|-----------|--------|----|
| Heuristic only (traffic-rules-v1) | 0.0192 ms | 0.0259 ms | 52,118 rps | 100% | 100% | 100% |
| Hybrid ML (traffic-hybrid-v1) | 5.5094 ms | 12.50 ms | 181.5 rps | 100% | 100% | 100% |

ML overhead: ~286x slower than heuristic-only due to numpy allocation and sklearn tree traversal.
Both modes achieve 100% precision/recall/F1 on canonical four-scenario benchmark.

---

## 6. Contract Conformance

TrafficAssessment v1.0.0 schema is FROZEN at contracts/traffic/traffic_assessment.schema.json.
ML signal appears only in top_signals[] field as "ml_anomaly_detected" string.

All 4 service test suites: PASSED
test_contract_conformance.py: PASSED

---

## 7. Fallback Behaviour

| Condition | Behaviour |
|-----------|-----------|
| isolation_forest.joblib missing | Graceful fallback to heuristic-only; no crash |
| Model load error | Warning logged; heuristic-only |
| ENABLE_ML_ANOMALY_DETECTOR=false | ML disabled at settings level |
| Telemetry absent | ML skipped; heuristic-only |
| Runtime inference exception | Exception caught, logged; heuristic result used |

---

## 8. Future Phases

| Phase | Task |
|-------|------|
| M1-5 | Real telemetry integration |
| M1-6 | Sliding window burst detector |
| M1-7 | Composite risk weighting |
| M1-8 | Confidence calibration |
| M1-9 | SHAP explainability |
| M1-11 | Drift detection |
| M1-12 | MLflow lifecycle |
