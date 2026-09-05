"""
Unit tests for SentinelScale Stage M3-8 Experimentation Harness & Comparative Metrics.
Validates scenario definitions, pod-seconds/replica-hours integration, divergence classification,
performance guardrail evaluation, result schema structure, and safety invariants.
"""

from pathlib import Path
import json
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCENARIOS_DIR = REPO_ROOT / "experiments" / "scenarios"
CONTRACTS_DIR = REPO_ROOT / "contracts" / "experiments"

from experiments.harness import (
    calculate_pod_seconds,
    classify_divergence,
    evaluate_performance_guardrails,
    validate_experiment_result_structure,
)


def test_scenario_files_exist_and_are_valid():
    expected_scenarios = [
        "scenario_a_normal",
        "scenario_b_sustained_high",
        "scenario_c_spike",
        "scenario_d_recovery",
        "scenario_e_burst"
    ]
    for scn_id in expected_scenarios:
        file_path = SCENARIOS_DIR / f"{scn_id}.json"
        assert file_path.exists(), f"Scenario file {file_path} must exist"
        data = json.loads(file_path.read_text(encoding="utf-8"))
        assert data["scenario_id"] == scn_id
        assert "name" in data
        assert "hpa_baseline" in data
        assert "workload" in data
        assert "performance_guardrails" in data
        assert data["hpa_baseline"]["min_replicas"] == 2
        assert data["hpa_baseline"]["max_replicas"] == 5


def test_calculate_pod_seconds_constant_series():
    # 2 replicas for 60 seconds = 120 pod-seconds, 120/3600 = 0.0333 replica-hours
    series = [(0.0, 2)]
    pod_sec, rep_hrs = calculate_pod_seconds(series, 60.0)
    assert pod_sec == 120.0
    assert rep_hrs == round(120.0 / 3600.0, 4)


def test_calculate_pod_seconds_stepped_series():
    # 0s to 10s: 2 pods (2 * 10 = 20)
    # 10s to 30s: 4 pods (4 * 20 = 80)
    # 30s to 40s: 2 pods (2 * 10 = 20)
    # Total 40s: 120 pod-seconds, 120 / 3600 = 0.0333 replica-hours
    series = [(0.0, 2), (10.0, 4), (30.0, 2)]
    pod_sec, rep_hrs = calculate_pod_seconds(series, 40.0)
    assert pod_sec == 120.0
    assert rep_hrs == round(120.0 / 3600.0, 4)


def test_classify_divergence_cases():
    assert classify_divergence([0, 0, 0])[0] == "agreement"
    assert classify_divergence([0, -1, -2])[0] == "sentinelscale_recommends_fewer"
    assert classify_divergence([0, 1, 2])[0] == "sentinelscale_recommends_more"
    assert classify_divergence([1, -1, 0])[0] == "mixed"
    assert classify_divergence([0, -2, 1])[1] == 2  # max diff


def test_evaluate_performance_guardrails_pass_and_fail():
    passed, data = evaluate_performance_guardrails(
        p95_latency_ms=45.0,
        error_rate=0.01,
        p95_guardrail_ms=1000.0,
        error_rate_guardrail=0.05
    )
    assert passed is True
    assert data["guardrails_passed"] is True

    failed, data = evaluate_performance_guardrails(
        p95_latency_ms=1200.0,
        error_rate=0.08,
        p95_guardrail_ms=1000.0,
        error_rate_guardrail=0.05
    )
    assert failed is False
    assert data["guardrails_passed"] is False


def test_validate_experiment_result_structure_valid():
    valid_sample = {
        "run_id": "EXP-20260906-001",
        "scenario_id": "scenario_a_normal",
        "scenario_name": "Scenario A — Normal",
        "start_time": "2026-09-06T00:00:00Z",
        "end_time": "2026-09-06T00:01:00Z",
        "duration_seconds": 60.0,
        "phases": [{"phase_name": "RESET", "timestamp": "2026-09-06T00:00:00Z", "elapsed_seconds": 0.0}],
        "workload_summary": {
            "total_requests": 500,
            "average_rps": 8.33,
            "peak_rps": 12.0,
            "error_rate": 0.0,
            "p50_latency_ms": 10.0,
            "p95_latency_ms": 30.0
        },
        "hpa_summary": {
            "initial_replicas": 2,
            "final_replicas": 2,
            "peak_replicas": 2,
            "min_replicas": 2,
            "pod_seconds": 120.0,
            "replica_hours": 0.0333
        },
        "sentinelscale_summary": {
            "initial_recommended_pods": 2,
            "final_recommended_pods": 2,
            "peak_recommended_pods": 2,
            "min_recommended_pods": 2,
            "pod_seconds": 120.0,
            "replica_hours": 0.0333,
            "decisions_count": 10,
            "action_distribution": {"HOLD": 10}
        },
        "comparison_summary": {
            "pod_seconds_delta": 0.0,
            "replica_hours_delta": 0.0,
            "max_replica_difference": 0,
            "divergence_classification": "agreement",
            "performance_guardrails_passed": True
        },
        "performance_guardrails": {
            "p95_latency_guardrail_ms": 1000.0,
            "observed_p95_latency_ms": 30.0,
            "error_rate_guardrail": 0.05,
            "observed_error_rate": 0.0,
            "guardrails_passed": True
        },
        "safety": {
            "dry_run": True,
            "shadow_mode": True,
            "sentinel_mutations_count": 0,
            "autonomous_actions_enabled": False
        }
    }
    errors = validate_experiment_result_structure(valid_sample)
    assert len(errors) == 0, f"Expected valid sample to have no errors, got: {errors}"


def test_validate_experiment_result_safety_invariants():
    invalid_safety = {
        "run_id": "EXP-20260906-001",
        "scenario_id": "scenario_a_normal",
        "scenario_name": "Scenario A — Normal",
        "start_time": "2026-09-06T00:00:00Z",
        "end_time": "2026-09-06T00:01:00Z",
        "duration_seconds": 60.0,
        "phases": [],
        "workload_summary": {},
        "hpa_summary": {},
        "sentinelscale_summary": {},
        "comparison_summary": {},
        "performance_guardrails": {},
        "safety": {
            "dry_run": False,  # VIOLATION
            "shadow_mode": False,  # VIOLATION
            "sentinel_mutations_count": 2,  # VIOLATION
            "autonomous_actions_enabled": True  # VIOLATION
        }
    }
    errors = validate_experiment_result_structure(invalid_safety)
    assert len(errors) >= 4
    assert any("dry_run" in e for e in errors)
    assert any("shadow_mode" in e for e in errors)
    assert any("sentinel_mutations_count" in e for e in errors)
    assert any("autonomous_actions_enabled" in e for e in errors)
