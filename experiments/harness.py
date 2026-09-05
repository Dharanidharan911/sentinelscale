"""
SentinelScale Stage M3-8: Experimentation Harness & Comparative Evaluator

Implements a repeatable, deterministic experiment runner that drives controlled
k6 workloads against Kubernetes, captures timestamp-aligned telemetry from
Kubernetes HPA, Prometheus, and SentinelScale shadow decisions, and computes
comparative resource usage (pod-seconds, replica-hours) and performance guardrails.

CRITICAL SAFETY INVARIANT:
- dry_run = True
- shadow_mode = True
- autonomous_actions_enabled = False
- 0 SentinelScale Kubernetes mutations
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "experiments" / "scenarios"
RESULTS_DIR = REPO_ROOT / "experiments" / "results"
CONTRACTS_DIR = REPO_ROOT / "contracts"


def calculate_pod_seconds(timeseries_replicas: List[Tuple[float, int]], total_duration_seconds: float) -> Tuple[float, float]:
    """
    Computes pod-seconds and replica-hours from a time-series of (elapsed_seconds, replica_count).
    Uses interval-weighted Riemann integration.

    pod_seconds = sum(replicas_i * delta_t_i)
    replica_hours = pod_seconds / 3600.0
    """
    if not timeseries_replicas:
        return 0.0, 0.0

    if len(timeseries_replicas) == 1:
        pod_sec = timeseries_replicas[0][1] * total_duration_seconds
        return round(pod_sec, 2), round(pod_sec / 3600.0, 4)

    # Sort by elapsed seconds
    sorted_points = sorted(timeseries_replicas, key=lambda x: x[0])
    total_pod_seconds = 0.0

    for i in range(len(sorted_points) - 1):
        t_curr, reps_curr = sorted_points[i]
        t_next, _ = sorted_points[i + 1]
        delta_t = max(0.0, t_next - t_curr)
        total_pod_seconds += reps_curr * delta_t

    # Add final segment from last sample to total duration if applicable
    last_t, last_reps = sorted_points[-1]
    if total_duration_seconds > last_t:
        total_pod_seconds += last_reps * (total_duration_seconds - last_t)

    replica_hours = total_pod_seconds / 3600.0
    return round(total_pod_seconds, 2), round(replica_hours, 4)


def classify_divergence(timeseries_deltas: List[int]) -> Tuple[str, int]:
    """
    Classifies decision divergence between SentinelScale recommendation and HPA desired replicas:
    - agreement: All deltas == 0
    - sentinelscale_recommends_fewer: All deltas <= 0 and at least one < 0
    - sentinelscale_recommends_more: All deltas >= 0 and at least one > 0
    - mixed: Contains both positive and negative deltas
    """
    if not timeseries_deltas:
        return "agreement", 0

    max_diff = max(abs(d) for d in timeseries_deltas)
    has_fewer = any(d < 0 for d in timeseries_deltas)
    has_more = any(d > 0 for d in timeseries_deltas)

    if has_fewer and has_more:
        classification = "mixed"
    elif has_fewer:
        classification = "sentinelscale_recommends_fewer"
    elif has_more:
        classification = "sentinelscale_recommends_more"
    else:
        classification = "agreement"

    return classification, max_diff


def evaluate_performance_guardrails(
    p95_latency_ms: float,
    error_rate: float,
    p95_guardrail_ms: float,
    error_rate_guardrail: float
) -> Tuple[bool, Dict[str, Any]]:
    """
    Evaluates whether workload performance remained within defined guardrails.
    """
    p95_passed = p95_latency_ms <= p95_guardrail_ms
    error_passed = error_rate <= error_rate_guardrail
    overall_passed = p95_passed and error_passed

    return overall_passed, {
        "p95_latency_guardrail_ms": p95_guardrail_ms,
        "observed_p95_latency_ms": round(p95_latency_ms, 2),
        "error_rate_guardrail": error_rate_guardrail,
        "observed_error_rate": round(error_rate, 4),
        "guardrails_passed": overall_passed
    }


def validate_experiment_result_structure(result: Dict[str, Any]) -> List[str]:
    """
    Validates an experiment result dictionary against the required M3-8 schema structure.
    Returns a list of validation errors (empty if valid).
    """
    errors = []
    required_top = [
        "run_id", "scenario_id", "scenario_name", "start_time", "end_time",
        "duration_seconds", "phases", "workload_summary", "hpa_summary",
        "sentinelscale_summary", "comparison_summary", "performance_guardrails", "safety"
    ]
    for field in required_top:
        if field not in result:
            errors.append(f"Missing required top-level field: {field}")

    # Safety checks
    safety = result.get("safety", {})
    if safety.get("dry_run") is not True:
        errors.append("Safety invariant violated: dry_run must be True")
    if safety.get("shadow_mode") is not True:
        errors.append("Safety invariant violated: shadow_mode must be True")
    if safety.get("sentinel_mutations_count") != 0:
        errors.append("Safety invariant violated: sentinel_mutations_count must be 0")
    if safety.get("autonomous_actions_enabled") is not False:
        errors.append("Safety invariant violated: autonomous_actions_enabled must be False")

    return errors


class ExperimentOrchestrator:
    """
    Orchestrates live experiment execution:
    - Sets up run metadata and phases
    - Executes k6 load generator
    - Periodically samples live Kubernetes, HPA, and SentinelScale Platform endpoints
    - Aligns time series and computes comparative metrics
    - Generates and writes structured results
    """

    def __init__(
        self,
        target_url: str = "http://localhost:8000",
        platform_url: str = "http://localhost:8003",
        results_dir: Optional[Path] = None
    ):
        self.target_url = target_url.rstrip("/")
        self.platform_url = platform_url.rstrip("/")
        self.results_dir = results_dir or RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def load_scenario(self, scenario_id_or_path: str) -> Dict[str, Any]:
        """Loads scenario configuration from file or ID."""
        if Path(scenario_id_or_path).exists():
            path = Path(scenario_id_or_path)
        else:
            path = SCENARIOS_DIR / f"{scenario_id_or_path}.json"
            if not path.exists():
                path = SCENARIOS_DIR / f"scenario_{scenario_id_or_path}.json"

        if not path.exists():
            raise FileNotFoundError(f"Scenario configuration not found: {scenario_id_or_path}")

        return json.loads(path.read_text(encoding="utf-8"))

    def sample_live_state(self, namespace: str = "sentinelscale", workload: str = "demo-api") -> Dict[str, Any]:
        """
        Samples live state from Kubernetes and Platform service.
        """
        sample: Dict[str, Any] = {
            "hpa_replicas": 2,
            "hpa_desired_replicas": 2,
            "hpa_cpu_percent": 0.0,
            "sentinel_recommended_pods": 2,
            "sentinel_action": "HOLD",
            "sentinel_reason": "Baseline state",
            "cpu_utilization": 0.0,
            "request_rate": 0.0,
            "p95_latency_ms": 0.0,
            "error_rate": 0.0
        }

        # 1. Query HPA state via kubectl
        try:
            cmd = ["kubectl", "get", "hpa", f"{workload}-hpa", "-n", namespace, "-o", "json"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                hpa_data = json.loads(proc.stdout)
                status = hpa_data.get("status", {})
                sample["hpa_replicas"] = status.get("currentReplicas", 2)
                sample["hpa_desired_replicas"] = status.get("desiredReplicas", sample["hpa_replicas"])
                current_metrics = status.get("currentMetrics", [])
                for m in current_metrics:
                    if m.get("type") == "Resource" and m.get("resource", {}).get("name") == "cpu":
                        sample["hpa_cpu_percent"] = m.get("resource", {}).get("current", {}).get("averageUtilization", 0.0)
        except Exception:
            pass

        # 2. Query SentinelScale Platform orchestrate/resource endpoint
        try:
            # Query platform via kubectl exec into platform pod or direct HTTP
            cmd = [
                "kubectl", "exec", "-n", namespace, "deployment/platform", "--",
                "python", "-c",
                f"import urllib.request, json; "
                f"req = urllib.request.Request('http://localhost:8003/api/v1/decision/orchestrate', "
                f"data=json.dumps({{'namespace': '{namespace}', 'workload': '{workload}'}}).encode(), "
                f"headers={{'Content-Type': 'application/json'}}); "
                f"print(urllib.request.urlopen(req, timeout=3).read().decode())"
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            if proc.returncode == 0:
                dec_data = json.loads(proc.stdout.strip())
                sample["sentinel_recommended_pods"] = dec_data.get("recommended_pods", 2)
                sample["sentinel_action"] = dec_data.get("action", "HOLD")
                sample["sentinel_reason"] = dec_data.get("reason", "")
        except Exception:
            pass

        return sample
