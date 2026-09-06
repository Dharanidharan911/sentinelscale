"""
Isolation Forest Training Tool for SentinelScale Module 1 (Traffic Intelligence).

Trains an unsupervised Isolation Forest model on the 7-dimensional feature vectors
extracted from legitimate baseline traffic (Scenario A: Steady Legitimate +
Scenario B: Legitimate Flash Crowd).

Evaluates the trained model on anomaly detection across Scenarios A, B, C, and D,
and serializes model weights to a compact joblib artifact.
"""

import argparse
import json
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

from app.pipeline.features import ExtractedTrafficFeatures, FeatureExtractor
from tools.generate_dataset import TrafficDatasetGenerator


FEATURE_NAMES = [
    "total_rps",
    "burst_ratio",
    "error_rate",
    "ip_concentration",
    "ua_anomaly_ratio",
    "single_endpoint_ratio",
    "data_completeness",
]


def extract_feature_array(records: List) -> np.ndarray:
    """Converts a list of DatasetRecord objects into a 2D numpy feature matrix."""
    matrix = []
    for r in records:
        f = r.features
        vector = [
            float(f["total_rps"]),
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
    """
    # 1. Generate Training Dataset (Legitimate Traffic Only)
    train_generator = TrafficDatasetGenerator(seed=seed)
    train_records = []
    for _ in range(samples_per_scenario):
        telemetry_a, label_a = train_generator.generate_scenario_a_sample()
        train_records.append(
            type("Rec", (), {
                "features": {
                    "total_rps": telemetry_a.total_rps,
                    "burst_ratio": round(telemetry_a.total_rps / telemetry_a.baseline_rps, 3) if telemetry_a.baseline_rps else 1.0,
                    "error_rate": telemetry_a.status_codes.error_rate if telemetry_a.status_codes else 0.0,
                    "ip_concentration": telemetry_a.top_ip_ratio or 0.0,
                    "ua_anomaly_ratio": telemetry_a.non_standard_ua_ratio or 0.0,
                    "single_endpoint_ratio": telemetry_a.single_endpoint_ratio or 0.0,
                    "data_completeness": 1.0,
                }
            })
        )
        telemetry_b, label_b = train_generator.generate_scenario_b_sample()
        train_records.append(
            type("Rec", (), {
                "features": {
                    "total_rps": telemetry_b.total_rps,
                    "burst_ratio": round(telemetry_b.total_rps / telemetry_b.baseline_rps, 3) if telemetry_b.baseline_rps else 1.0,
                    "error_rate": telemetry_b.status_codes.error_rate if telemetry_b.status_codes else 0.0,
                    "ip_concentration": telemetry_b.top_ip_ratio or 0.0,
                    "ua_anomaly_ratio": telemetry_b.non_standard_ua_ratio or 0.0,
                    "single_endpoint_ratio": telemetry_b.single_endpoint_ratio or 0.0,
                    "data_completeness": 1.0,
                }
            })
        )

    X_train = extract_feature_array(train_records)

    # 2. Fit Unsupervised Isolation Forest
    model = IsolationForest(
        n_estimators=n_estimators,
        max_samples="auto",
        contamination=contamination,
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(X_train)

    # 3. Evaluate on an Independent Test Split with All 4 Scenarios
    test_generator = TrafficDatasetGenerator(seed=seed + 999)
    test_records = test_generator.generate_dataset(samples_per_scenario=100)
    X_test = extract_feature_array(test_records)

    # Predictions: 1 for inlier (normal), -1 for outlier (anomaly)
    preds = model.predict(X_test)
    # Decision function: lower values mean more abnormal
    decision_scores = model.decision_function(X_test)

    # Breakdown detection by scenario
    scenario_stats = {"A": {"inlier": 0, "outlier": 0},
                      "B": {"inlier": 0, "outlier": 0},
                      "C": {"inlier": 0, "outlier": 0},
                      "D": {"inlier": 0, "outlier": 0}}

    for r, p in zip(test_records, preds):
        s_id = r.scenario_id
        tag = "inlier" if p == 1 else "outlier"
        scenario_stats[s_id][tag] += 1

    evaluation_report = {
        "training": {
            "samples_trained": len(X_train),
            "features_used": FEATURE_NAMES,
            "n_estimators": n_estimators,
            "contamination": contamination,
            "seed": seed,
        },
        "evaluation_test_split": {
            "total_test_samples": len(test_records),
            "scenario_breakdown": scenario_stats,
            "min_decision_score": float(np.min(decision_scores)),
            "max_decision_score": float(np.max(decision_scores)),
            "mean_decision_score": float(np.mean(decision_scores)),
        }
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


if __name__ == "__main__":
    main()
