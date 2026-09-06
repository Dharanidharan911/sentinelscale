"""
Isolation Forest Training Tool for SentinelScale Module 1 (Traffic Intelligence).

Trains an unsupervised Isolation Forest model on the 7-dimensional feature vectors
extracted from legitimate baseline traffic (Scenario A: Steady Legitimate +
Scenario B: Legitimate Flash Crowd).

Feature extraction uses FeatureExtractor.extract() exclusively -- the same path
used at inference time -- to guarantee training/inference consistency.

Feature normalization:
  total_rps is divided by TOTAL_RPS_SCALE (imported from ml_detector) so it
  occupies [0, ~1] alongside the other ratio features. All other features are
  already ratios in [0, 1]. The same constant is applied at inference.

Evaluates the trained model on anomaly detection across Scenarios A, B, C, D,
and serializes model weights to a compact joblib artifact.

Reproduce:
  python services/traffic-intelligence/tools/train_isolation_forest.py \
    --samples-per-scenario 500 --seed 42 --n-estimators 100 --contamination 0.02
"""

import argparse
from dataclasses import asdict
from pathlib import Path
import sys
from typing import Dict, List, Tuple

# Ensure services/traffic-intelligence is on sys.path
_service_root = Path(__file__).resolve().parents[1]
if str(_service_root) not in sys.path:
    sys.path.insert(0, str(_service_root))

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from app.pipeline.features import FeatureExtractor
from app.pipeline.ml_detector import FEATURE_NAMES, TOTAL_RPS_SCALE
from tools.generate_dataset import TrafficDatasetGenerator


def extract_feature_matrix(records: List) -> np.ndarray:
    """
    Converts DatasetRecord objects into a 2D numpy feature matrix.

    Uses the canonical FEATURE_NAMES ordering and applies the same
    TOTAL_RPS_SCALE normalization as ml_detector.detect().
    """
    matrix = []
    for r in records:
        f = r.features  # dict from asdict(ExtractedTrafficFeatures)
        vector = [
            float(f["total_rps"]) / TOTAL_RPS_SCALE,  # normalized [0, ~1]
            float(f["burst_ratio"]),
            float(f["error_rate"]),
            float(f["ip_concentration"]),
            float(f["ua_anomaly_ratio"]),
            float(f["single_endpoint_ratio"]),
            float(f["data_completeness"]),
        ]
        matrix.append(vector)
    return np.array(matrix, dtype=np.float32)


def train_isolation_forest(
    samples_per_scenario: int = 500,
    seed: int = 42,
    contamination: float = 0.02,
    n_estimators: int = 100,
) -> Tuple[IsolationForest, Dict]:
    """
    Trains Isolation Forest strictly on legitimate baseline traffic (Scenarios A + B).
    Evaluates sensitivity on test splits of Scenarios A, B, C, D.

    Feature extraction is delegated entirely to the generate_dataset pipeline which
    calls FeatureExtractor.extract() -- the same code path used at inference time.
    """
    # 1. Generate Training Dataset (Legitimate Traffic Only) via generate_dataset
    #    which calls FeatureExtractor.extract() for each sample.
    train_generator = TrafficDatasetGenerator(seed=seed)
    train_records = []
    for _ in range(samples_per_scenario):
        telemetry_a, _ = train_generator.generate_scenario_a_sample()
        features_a = FeatureExtractor.extract(telemetry_a)
        train_records.append(type("Rec", (), {"features": asdict(features_a)})())

        telemetry_b, _ = train_generator.generate_scenario_b_sample()
        features_b = FeatureExtractor.extract(telemetry_b)
        train_records.append(type("Rec", (), {"features": asdict(features_b)})())

    X_train = extract_feature_matrix(train_records)

    print(f"Training set shape: {X_train.shape}")
    print(f"  total_rps (normalized): min={X_train[:,0].min():.4f} max={X_train[:,0].max():.4f}")
    print(f"  burst_ratio:            min={X_train[:,1].min():.4f} max={X_train[:,1].max():.4f}")
    print(f"  error_rate:             min={X_train[:,2].min():.4f} max={X_train[:,2].max():.4f}")

    # 2. Fit Unsupervised Isolation Forest
    model = IsolationForest(
        n_estimators=n_estimators,
        max_samples="auto",
        contamination=contamination,
        random_state=seed,
        n_jobs=1,  # single-threaded: we optimize for per-request inference, not batch
    )
    model.fit(X_train)

    # 3. Evaluate on an Independent Test Split with All 4 Scenarios
    #    Uses generate_dataset() which calls FeatureExtractor.extract() internally.
    test_generator = TrafficDatasetGenerator(seed=seed + 999)
    test_records = test_generator.generate_dataset(samples_per_scenario=100)
    X_test = extract_feature_matrix(test_records)

    # decision_function: lower values = more anomalous
    decision_scores = model.decision_function(X_test)
    # Derive predictions from decision_function sign (same as predict() does internally)
    preds = np.where(decision_scores >= 0.0, 1, -1)

    # Breakdown detection by scenario
    scenario_stats = {
        "A": {"inlier": 0, "outlier": 0},
        "B": {"inlier": 0, "outlier": 0},
        "C": {"inlier": 0, "outlier": 0},
        "D": {"inlier": 0, "outlier": 0},
    }
    for r, p in zip(test_records, preds):
        s_id = r.scenario_id
        tag = "inlier" if p == 1 else "outlier"
        scenario_stats[s_id][tag] += 1

    evaluation_report = {
        "training": {
            "samples_trained": len(X_train),
            "features_used": FEATURE_NAMES,
            "normalization": {"total_rps": f"/ {TOTAL_RPS_SCALE}"},
            "n_estimators": n_estimators,
            "contamination": contamination,
            "seed": seed,
            "feature_extraction": "FeatureExtractor.extract() (canonical path)",
        },
        "evaluation_test_split": {
            "total_test_samples": len(test_records),
            "scenario_breakdown": scenario_stats,
            "min_decision_score": float(np.min(decision_scores)),
            "max_decision_score": float(np.max(decision_scores)),
            "mean_decision_score": float(np.mean(decision_scores)),
        },
    }

    return model, evaluation_report


def main():
    parser = argparse.ArgumentParser(description="Train Isolation Forest Anomaly Detector.")
    parser.add_argument("--samples-per-scenario", type=int, default=500, help="Training samples per scenario (A and B)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--n-estimators", type=int, default=100, help="Number of trees in forest")
    parser.add_argument("--contamination", type=float, default=0.02, help="Contamination factor")
    parser.add_argument(
        "--output",
        type=str,
        default=str(_service_root / "app" / "models" / "weights" / "isolation_forest.joblib"),
        help="Path to save serialized model weights",
    )
    args = parser.parse_args()

    print("Training Isolation Forest on Legitimate Traffic Baselines (Scenarios A & B)...")
    print(f"  Feature normalization: total_rps / {TOTAL_RPS_SCALE} (all features -> [0,1] scale)")
    model, eval_report = train_isolation_forest(
        samples_per_scenario=args.samples_per_scenario,
        seed=args.seed,
        contamination=args.contamination,
        n_estimators=args.n_estimators,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out_path, compress=3)

    print(f"Model successfully saved to: {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")
    print("-" * 60)
    print("Test Evaluation Breakdown across Scenarios (100 samples each):")
    for s_id, stats in eval_report["evaluation_test_split"]["scenario_breakdown"].items():
        name = {"A": "Steady Legitimate", "B": "Flash Crowd Surge", "C": "Hostile L7 Attack", "D": "Mixed Traffic"}[s_id]
        print(f"  Scenario {s_id} ({name:<20}): Inliers={stats['inlier']:<3} | Outliers (Anomalies)={stats['outlier']:<3}")
    print("-" * 60)
    print(f"Decision score range: [{eval_report['evaluation_test_split']['min_decision_score']:.4f}, {eval_report['evaluation_test_split']['max_decision_score']:.4f}]")
    print("-" * 60)


if __name__ == "__main__":
    main()
