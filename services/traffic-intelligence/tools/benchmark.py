"""
Quantitative Benchmark Evaluation Tool for Module 1 (Traffic Intelligence).

Evaluates the CURRENT heuristic Traffic Intelligence implementation against
reproducible synthetic scenario datasets generated across canonical scenarios:
  Scenario A: Steady Legitimate
  Scenario B: Legitimate Flash Crowd
  Scenario C: Hostile L7
  Scenario D: Mixed Traffic

Measures:
  - Confusion matrix
  - Precision, Recall, F1
  - False Positive Rate (FPR), False Negative Rate (FNR)
  - Inference latency (mean, p50, p95, p99)
  - Throughput (assessments/sec)
  - Confidence distribution
"""

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Dict, List

# Ensure services/traffic-intelligence is on sys.path
_service_root = Path(__file__).resolve().parents[1]
if str(_service_root) not in sys.path:
    sys.path.insert(0, str(_service_root))

from app.models.traffic import (
    AssessmentRequest,
    StatusCodeDistribution,
    TrafficClassification,
    TrafficTelemetryInput,
)
from app.pipeline.engine import TrafficIntelligenceEngine
from tools.generate_dataset import TrafficDatasetGenerator


def run_benchmark(samples_per_scenario: int = 250, seed: int = 42) -> Dict:
    generator = TrafficDatasetGenerator(seed=seed)
    records = generator.generate_dataset(samples_per_scenario=samples_per_scenario)

    engine = TrafficIntelligenceEngine()

    total_samples = len(records)
    latencies_ms = []

    # Map scenario labels to binary/multiclass evaluations
    # Scenario labels: LEGITIMATE (A, B), MALICIOUS (C), MIXED (D)
    # Predicted classifications: legitimate, suspicious, malicious, unknown

    results = []

    for r in records:
        telemetry = TrafficTelemetryInput(**r.raw_telemetry)
        req = AssessmentRequest(
            window_seconds=r.window_seconds,
            telemetry=telemetry
        )

        t0 = time.perf_counter()
        assessment = engine.evaluate(req)
        t1 = time.perf_counter()

        latencies_ms.append((t1 - t0) * 1000.0)

        results.append({
            "scenario_id": r.scenario_id,
            "scenario_name": r.scenario_name,
            "scenario_derived_label": r.scenario_derived_label,
            "predicted_classification": assessment.classification.value,
            "risk_score": assessment.risk_score,
            "legitimacy_score": assessment.legitimacy_score,
            "confidence": assessment.confidence,
            "legitimate_rps_estimate": assessment.legitimate_rps_estimate,
            "suspicious_rps_estimate": assessment.suspicious_rps_estimate,
            "total_rps": assessment.total_rps,
        })

    latencies_ms.sort()
    p50 = latencies_ms[int(total_samples * 0.50)]
    p95 = latencies_ms[int(total_samples * 0.95)]
    p99 = latencies_ms[int(total_samples * 0.99)]
    mean_lat = sum(latencies_ms) / total_samples
    total_time_s = sum(latencies_ms) / 1000.0
    throughput = round(total_samples / total_time_s, 1) if total_time_s > 0 else 0.0

    # Binary Classification Metrics for Threat Detection (Malicious vs Non-Malicious)
    # Positive class = MALICIOUS (Threat detected)
    # Negative class = LEGITIMATE (Safe traffic)
    # Note: MIXED contains both, evaluate how it is handled
    tp = 0
    fp = 0
    tn = 0
    fn = 0

    # Multiclass confusion matrix [Actual Label][Predicted Classification]
    # Rows: Actual (LEGITIMATE, MALICIOUS, MIXED)
    # Cols: Predicted (legitimate, suspicious, malicious, unknown)
    classes_actual = ["LEGITIMATE", "MALICIOUS", "MIXED"]
    classes_pred = ["legitimate", "suspicious", "malicious", "unknown"]
    confusion_matrix = {a: {p: 0 for p in classes_pred} for a in classes_actual}

    confidence_buckets = {"0.0-0.4": 0, "0.4-0.7": 0, "0.7-1.0": 0}

    for res in results:
        actual = res["scenario_derived_label"]
        pred = res["predicted_classification"]
        confusion_matrix[actual][pred] += 1

        conf = res["confidence"]
        if conf < 0.4:
            confidence_buckets["0.0-0.4"] += 1
        elif conf < 0.7:
            confidence_buckets["0.4-0.7"] += 1
        else:
            confidence_buckets["0.7-1.0"] += 1

        # Binary Threat Detection evaluation (considering Legitimate vs Malicious ground truth)
        if actual == "MALICIOUS":
            if pred in ["malicious", "suspicious"]:
                tp += 1
            else:
                fn += 1
        elif actual == "LEGITIMATE":
            if pred in ["malicious", "suspicious"]:
                fp += 1
            else:
                tn += 1

    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1 = round(2 * (precision * recall) / (precision + recall), 4) if (precision + recall) > 0 else 0.0
    fpr = round(fp / (fp + tn), 4) if (fp + tn) > 0 else 0.0
    fnr = round(fn / (fn + tp), 4) if (fn + tp) > 0 else 0.0

    return {
        "dataset": {
            "samples_per_scenario": samples_per_scenario,
            "total_observations": total_samples,
            "seed": seed,
            "scenario_counts": {
                "LEGITIMATE (A+B)": samples_per_scenario * 2,
                "MALICIOUS (C)": samples_per_scenario,
                "MIXED (D)": samples_per_scenario,
            },
        },
        "performance": {
            "mean_latency_ms": round(mean_lat, 4),
            "p50_latency_ms": round(p50, 4),
            "p95_latency_ms": round(p95, 4),
            "p99_latency_ms": round(p99, 4),
            "throughput_rps": throughput,
        },
        "binary_threat_metrics": {
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "false_positive_rate": fpr,
            "false_negative_rate": fnr,
        },
        "multiclass_confusion_matrix": confusion_matrix,
        "confidence_distribution": confidence_buckets,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark heuristic Traffic Intelligence pipeline.")
    parser.add_argument("--samples-per-scenario", type=int, default=250, help="Number of samples per scenario (total = 4x)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for scenario dataset generation")
    args = parser.parse_args()

    benchmark_data = run_benchmark(samples_per_scenario=args.samples_per_scenario, seed=args.seed)

    print("=" * 60)
    print(" SentinelScale M1: Traffic Intelligence Heuristic Baseline Benchmark")
    print("=" * 60)
    print(f"Total observations: {benchmark_data['dataset']['total_observations']}")
    print(f"Seed: {benchmark_data['dataset']['seed']}")
    print("-" * 60)
    print("Latency & Throughput:")
    print(f"  Mean latency: {benchmark_data['performance']['mean_latency_ms']} ms")
    print(f"  P50 latency:  {benchmark_data['performance']['p50_latency_ms']} ms")
    print(f"  P95 latency:  {benchmark_data['performance']['p95_latency_ms']} ms")
    print(f"  P99 latency:  {benchmark_data['performance']['p99_latency_ms']} ms")
    print(f"  Throughput:   {benchmark_data['performance']['throughput_rps']} assessments/sec")
    print("-" * 60)
    print("Binary Threat Detection (Legitimate vs Malicious):")
    metrics = benchmark_data["binary_threat_metrics"]
    print(f"  TP: {metrics['true_positives']} | FP: {metrics['false_positives']}")
    print(f"  TN: {metrics['true_negatives']} | FN: {metrics['false_negatives']}")
    print(f"  Precision: {metrics['precision'] * 100:.2f}%")
    print(f"  Recall:    {metrics['recall'] * 100:.2f}%")
    print(f"  F1 Score:  {metrics['f1'] * 100:.2f}%")
    print(f"  FPR:       {metrics['false_positive_rate'] * 100:.2f}%")
    print(f"  FNR:       {metrics['false_negative_rate'] * 100:.2f}%")
    print("-" * 60)
    print("Multiclass Confusion Matrix [Actual \\ Predicted]:")
    cm = benchmark_data["multiclass_confusion_matrix"]
    headers = ["legitimate", "suspicious", "malicious", "unknown"]
    print(f"{'Actual':<12} | " + " | ".join(f"{h:<10}" for h in headers))
    for actual in ["LEGITIMATE", "MALICIOUS", "MIXED"]:
        row = " | ".join(f"{cm[actual][h]:<10}" for h in headers)
        print(f"{actual:<12} | {row}")
    print("-" * 60)
    print("Confidence Distribution:", benchmark_data["confidence_distribution"])
    print("=" * 60)


if __name__ == "__main__":
    main()
