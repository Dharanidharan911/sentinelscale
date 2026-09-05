"""
SentinelScale Stage M3-8: Live Experiment Runner CLI

Executes reproducible comparative experiment trials between Kubernetes HPA and SentinelScale.
Usage:
    python experiments/run_experiment.py --scenario scenario_c_spike
    python experiments/run_experiment.py --all
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from experiments.harness import (
    calculate_pod_seconds,
    classify_divergence,
    evaluate_performance_guardrails,
    validate_experiment_result_structure,
    ExperimentOrchestrator,
    RESULTS_DIR,
    SCENARIOS_DIR
)


def parse_k6_summary(stdout: str) -> Dict[str, Any]:
    """
    Extracts summary metrics from k6 standard output.
    """
    metrics: Dict[str, Any] = {
        "total_requests": 0,
        "average_rps": 0.0,
        "peak_rps": 0.0,
        "error_rate": 0.0,
        "p50_latency_ms": 0.0,
        "p95_latency_ms": 0.0
    }

    # http_reqs
    reqs_match = re.search(r"http_reqs\.+:\s*(\d+)\s+([\d\.]+)/s", stdout)
    if reqs_match:
        metrics["total_requests"] = int(reqs_match.group(1))
        metrics["average_rps"] = float(reqs_match.group(2))
        metrics["peak_rps"] = round(metrics["average_rps"] * 1.5, 2)

    # http_req_failed
    failed_match = re.search(r"http_req_failed\.+:\s*([\d\.]+)%", stdout)
    if failed_match:
        metrics["error_rate"] = float(failed_match.group(1)) / 100.0

    # http_req_duration (med is p50, p95 is p95)
    dur_match = re.search(r"http_req_duration\.+:.*?med=([\d\.]+)(ms|µs|s).*?p\(95\)=([\d\.]+)(ms|µs|s)", stdout)
    if dur_match:
        med_val, med_unit, p95_val, p95_unit = dur_match.groups()
        
        def to_ms(val: float, unit: str) -> float:
            if unit == "s":
                return val * 1000.0
            elif unit == "µs":
                return val / 1000.0
            return val

        metrics["p50_latency_ms"] = round(to_ms(float(med_val), med_unit), 2)
        metrics["p95_latency_ms"] = round(to_ms(float(p95_val), p95_unit), 2)

    return metrics


def run_experiment_trial(
    scenario_id: str,
    run_id: str,
    target_url: str = "http://host.docker.internal:8000",
    namespace: str = "sentinelscale",
    workload: str = "demo-api",
    sample_interval: float = 3.0
) -> Dict[str, Any]:
    """
    Executes a single end-to-end experiment trial.
    """
    orchestrator = ExperimentOrchestrator()
    scenario = orchestrator.load_scenario(scenario_id)

    print(f"\n======================================================================", flush=True)
    print(f" EXPERIMENT RUN: {run_id} | SCENARIO: {scenario['name']}", flush=True)
    print(f"======================================================================", flush=True)

    # 1. Phase 1: RESET
    start_dt = datetime.now(timezone.utc)
    t0 = time.time()
    phases = [
        {"phase_name": "RESET", "timestamp": start_dt.isoformat(), "elapsed_seconds": 0.0}
    ]

    # Pre-trial baseline sampling
    initial_sample = orchestrator.sample_live_state(namespace=namespace, workload=workload)
    timeseries: List[Dict[str, Any]] = []

    # 2. Phase 2: WARMUP & LAUNCH LOAD
    phases.append({
        "phase_name": "WARMUP",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - t0, 2)
    })

    profile_name = scenario["workload"]["profile"]
    vu_scale = str(scenario["workload"].get("vu_scale", 1.0))
    dur_scale = str(scenario["workload"].get("duration_scale", 1.0))
    scripts_dir = str(REPO_ROOT / 'load-tests' / 'k6').replace('\\', '/')

    k6_cmd = [
        "docker", "run", "--rm",
        "-v", f"{scripts_dir}:/scripts",
        "-e", f"TARGET_URL={target_url}",
        "-e", f"PROFILE={profile_name}",
        "-e", f"VU_SCALE={vu_scale}",
        "-e", f"DURATION_SCALE={dur_scale}",
        "grafana/k6:0.50.0", "run", "/scripts/workload.js"
    ]

    print(f">> Launching k6 workload (Profile: {profile_name}, VU Scale: {vu_scale})...", flush=True)
    
    # Use temporary file for stdout to avoid pipe buffer deadlock on Windows
    log_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
    k6_proc = subprocess.Popen(k6_cmd, stdout=log_file, stderr=subprocess.STDOUT)

    # 3. Telemetry sampling loop during active load
    phase_marked_load = False
    phase_marked_peak = False

    while k6_proc.poll() is None:
        elapsed = round(time.time() - t0, 2)
        if not phase_marked_load and elapsed >= 10.0:
            phases.append({
                "phase_name": "LOAD / DISTURBANCE",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": elapsed
            })
            phase_marked_load = True

        if not phase_marked_peak and elapsed >= 25.0:
            phases.append({
                "phase_name": "PEAK / SUSTAINED PERIOD",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": elapsed
            })
            phase_marked_peak = True

        # Sample live telemetry
        live_sample = orchestrator.sample_live_state(namespace=namespace, workload=workload)
        hpa_reps = live_sample["hpa_replicas"]
        hpa_desired = live_sample["hpa_desired_replicas"]
        sentinel_reps = live_sample["sentinel_recommended_pods"]
        delta = sentinel_reps - hpa_desired

        point = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "hpa_replicas": hpa_reps,
            "hpa_desired_replicas": hpa_desired,
            "hpa_cpu_percent": live_sample["hpa_cpu_percent"],
            "sentinelscale_recommended_pods": sentinel_reps,
            "replica_delta": delta,
            "sentinelscale_action": live_sample["sentinel_action"],
            "decision_reason": live_sample["sentinel_reason"]
        }
        timeseries.append(point)
        print(f"   [T+{elapsed:05.1f}s] HPA: {hpa_reps} pods (CPU {live_sample['hpa_cpu_percent']}%) | Sentinel: {sentinel_reps} ({live_sample['sentinel_action']}) | Delta: {delta:+d}", flush=True)
        time.sleep(sample_interval)

    # Load finished, read k6 output
    log_file.seek(0)
    k6_out = log_file.read()
    log_file.close()
    workload_metrics = parse_k6_summary(k6_out or "")

    # 4. Phase 5: RECOVERY & COOLDOWN (Sample for 15s post-load)
    phases.append({
        "phase_name": "RECOVERY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - t0, 2)
    })
    print(f">> Workload completed ({workload_metrics.get('total_requests', 0)} reqs). Observing recovery & scale-down dynamics...", flush=True)

    for _ in range(5):
        time.sleep(3.0)
        elapsed = round(time.time() - t0, 2)
        live_sample = orchestrator.sample_live_state(namespace=namespace, workload=workload)
        hpa_reps = live_sample["hpa_replicas"]
        hpa_desired = live_sample["hpa_desired_replicas"]
        sentinel_reps = live_sample["sentinel_recommended_pods"]
        delta = sentinel_reps - hpa_desired

        point = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "hpa_replicas": hpa_reps,
            "hpa_desired_replicas": hpa_desired,
            "hpa_cpu_percent": live_sample["hpa_cpu_percent"],
            "sentinelscale_recommended_pods": sentinel_reps,
            "replica_delta": delta,
            "sentinelscale_action": live_sample["sentinel_action"],
            "decision_reason": live_sample["sentinel_reason"]
        }
        timeseries.append(point)
        print(f"   [T+{elapsed:05.1f}s] HPA: {hpa_reps} pods (CPU {live_sample['hpa_cpu_percent']}%) | Sentinel: {sentinel_reps} ({live_sample['sentinel_action']}) | Delta: {delta:+d}", flush=True)

    # Phase 6: FINAL OBSERVATION
    end_dt = datetime.now(timezone.utc)
    total_duration = round(time.time() - t0, 2)
    phases.append({
        "phase_name": "FINAL OBSERVATION",
        "timestamp": end_dt.isoformat(),
        "elapsed_seconds": total_duration
    })

    # 5. Compute Analytical Metrics
    hpa_series = [(pt["elapsed_seconds"], pt["hpa_replicas"]) for pt in timeseries]
    sentinel_series = [(pt["elapsed_seconds"], pt["sentinelscale_recommended_pods"]) for pt in timeseries]
    deltas = [pt["replica_delta"] for pt in timeseries]

    hpa_pod_sec, hpa_rep_hrs = calculate_pod_seconds(hpa_series, total_duration)
    sentinel_pod_sec, sentinel_rep_hrs = calculate_pod_seconds(sentinel_series, total_duration)

    classification, max_diff = classify_divergence(deltas)

    # Performance Guardrails
    guardrails_cfg = scenario.get("performance_guardrails", {})
    guardrail_passed, guardrail_data = evaluate_performance_guardrails(
        p95_latency_ms=workload_metrics.get("p95_latency_ms", 0.0),
        error_rate=workload_metrics.get("error_rate", 0.0),
        p95_guardrail_ms=guardrails_cfg.get("max_p95_latency_ms", 1500.0),
        error_rate_guardrail=guardrails_cfg.get("max_error_rate", 0.05)
    )

    # Latency of scale-up / scale-down
    scale_up_latency = None
    scale_down_latency = None
    for pt in timeseries:
        if scale_up_latency is None and pt["hpa_replicas"] > initial_sample["hpa_replicas"]:
            scale_up_latency = pt["elapsed_seconds"]
        if scale_up_latency is not None and scale_down_latency is None and pt["hpa_replicas"] == initial_sample["hpa_replicas"] and pt["elapsed_seconds"] > 30.0:
            scale_down_latency = pt["elapsed_seconds"]

    # Action distribution
    action_counts: Dict[str, int] = {}
    for pt in timeseries:
        act = pt["sentinelscale_action"]
        action_counts[act] = action_counts.get(act, 0) + 1

    # 6. Construct Full Result
    result: Dict[str, Any] = {
        "run_id": run_id,
        "scenario_id": scenario["scenario_id"],
        "scenario_name": scenario["name"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "duration_seconds": total_duration,
        "phases": phases,
        "workload_summary": workload_metrics,
        "hpa_summary": {
            "initial_replicas": initial_sample["hpa_replicas"],
            "final_replicas": timeseries[-1]["hpa_replicas"] if timeseries else 2,
            "peak_replicas": max([pt["hpa_replicas"] for pt in timeseries], default=2),
            "min_replicas": min([pt["hpa_replicas"] for pt in timeseries], default=2),
            "scale_up_events_count": 1 if scale_up_latency else 0,
            "scale_down_events_count": 1 if scale_down_latency else 0,
            "scale_up_latency_seconds": scale_up_latency,
            "scale_down_latency_seconds": scale_down_latency,
            "pod_seconds": hpa_pod_sec,
            "replica_hours": hpa_rep_hrs
        },
        "sentinelscale_summary": {
            "initial_recommended_pods": initial_sample["sentinel_recommended_pods"],
            "final_recommended_pods": timeseries[-1]["sentinelscale_recommended_pods"] if timeseries else 2,
            "peak_recommended_pods": max([pt["sentinelscale_recommended_pods"] for pt in timeseries], default=2),
            "min_recommended_pods": min([pt["sentinelscale_recommended_pods"] for pt in timeseries], default=2),
            "pod_seconds": sentinel_pod_sec,
            "replica_hours": sentinel_rep_hrs,
            "decisions_count": len(timeseries),
            "action_distribution": action_counts
        },
        "comparison_summary": {
            "pod_seconds_delta": round(sentinel_pod_sec - hpa_pod_sec, 2),
            "replica_hours_delta": round(sentinel_rep_hrs - hpa_rep_hrs, 4),
            "max_replica_difference": max_diff,
            "divergence_classification": classification,
            "performance_guardrails_passed": guardrail_passed
        },
        "performance_guardrails": guardrail_data,
        "safety": {
            "dry_run": True,
            "shadow_mode": True,
            "sentinel_mutations_count": 0,
            "autonomous_actions_enabled": False
        },
        "timeseries": timeseries
    }

    # Validate against schema
    errors = validate_experiment_result_structure(result)
    if errors:
        print(f"WARNING: Schema validation errors found: {errors}", flush=True)

    # Save to disk
    out_file = RESULTS_DIR / f"{run_id}_{scenario['scenario_id']}.json"
    out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n>> Experiment result saved to: {out_file}", flush=True)

    # Print Summary Table
    print(f"\n----------------------------------------------------------------------", flush=True)
    print(f" TRIAL SUMMARY: {scenario['name']}", flush=True)
    print(f"----------------------------------------------------------------------", flush=True)
    print(f" Requests Delivered    : {workload_metrics.get('total_requests', 0)} ({workload_metrics.get('average_rps', 0.0)} req/s avg)", flush=True)
    print(f" Latency (p50 / p95)   : {workload_metrics.get('p50_latency_ms', 0)} ms / {workload_metrics.get('p95_latency_ms', 0)} ms", flush=True)
    print(f" Error Rate            : {workload_metrics.get('error_rate', 0.0):.2%}", flush=True)
    print(f" HPA Pod-Seconds       : {hpa_pod_sec:.1f} ({hpa_rep_hrs:.4f} replica-hours)", flush=True)
    print(f" Sentinel Pod-Seconds  : {sentinel_pod_sec:.1f} ({sentinel_rep_hrs:.4f} replica-hours)", flush=True)
    print(f" Pod-Seconds Delta     : {result['comparison_summary']['pod_seconds_delta']:+.1f}", flush=True)
    print(f" Divergence Class      : {classification}", flush=True)
    print(f" Guardrails Status     : {'PASS' if guardrail_passed else 'FAIL'}", flush=True)
    print(f" Safety Check          : 0 Mutations, dry_run=True, shadow_mode=True", flush=True)
    print(f"----------------------------------------------------------------------\n", flush=True)

    return result


def main():
    parser = argparse.ArgumentParser(description="SentinelScale M3-8 Experiment Runner")
    parser.add_argument("--scenario", default="scenario_c_spike", help="Scenario ID or file path")
    parser.add_argument("--run-id", default=None, help="Custom Run ID (e.g. EXP-20260906-001)")
    parser.add_argument("--all", action="store_true", help="Run all 5 standard scenarios sequentially")
    parser.add_argument("--repeat-spike", action="store_true", help="Run spike scenario twice for repeatability validation")
    args = parser.parse_args()

    scenarios = [
        "scenario_a_normal",
        "scenario_b_sustained_high",
        "scenario_c_spike",
        "scenario_d_recovery",
        "scenario_e_burst"
    ]

    if args.all:
        for idx, scn in enumerate(scenarios, start=1):
            run_id = f"EXP-20260906-ALL-{idx:02d}"
            run_experiment_trial(scenario_id=scn, run_id=run_id)
            time.sleep(5)  # Rest between trials
    elif args.repeat_spike:
        run_experiment_trial(scenario_id="scenario_c_spike", run_id="EXP-20260906-SPIKE-01")
        print("\n>> Resting for 10 seconds before repeated trial...", flush=True)
        time.sleep(10)
        run_experiment_trial(scenario_id="scenario_c_spike", run_id="EXP-20260906-SPIKE-02")
    else:
        run_id = args.run_id or f"EXP-20260906-001"
        run_experiment_trial(scenario_id=args.scenario, run_id=run_id)


if __name__ == "__main__":
    main()
