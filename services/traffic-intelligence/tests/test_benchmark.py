import pytest
from app.models.traffic import TrafficClassification
from tools.benchmark import run_benchmark
from tools.generate_dataset import ScenarioLabel, TrafficDatasetGenerator


def test_traffic_dataset_generator_determinism():
    """Verify that dataset generator produces identical data given the same seed."""
    gen1 = TrafficDatasetGenerator(seed=123)
    gen2 = TrafficDatasetGenerator(seed=123)

    data1 = gen1.generate_dataset(samples_per_scenario=5)
    data2 = gen2.generate_dataset(samples_per_scenario=5)

    assert len(data1) == 20
    assert len(data2) == 20

    for r1, r2 in zip(data1, data2):
        assert r1.scenario_id == r2.scenario_id
        assert r1.scenario_derived_label == r2.scenario_derived_label
        assert r1.raw_telemetry == r2.raw_telemetry
        assert r1.features == r2.features


def test_traffic_dataset_generator_labels():
    gen = TrafficDatasetGenerator(seed=42)
    records = gen.generate_dataset(samples_per_scenario=10)

    labels = {r.scenario_derived_label for r in records}
    assert labels == {ScenarioLabel.LEGITIMATE, ScenarioLabel.MALICIOUS, ScenarioLabel.MIXED}


def test_benchmark_execution():
    """Verify that benchmark runner executes cleanly and returns expected metric structure."""
    results = run_benchmark(samples_per_scenario=10, seed=42)

    assert results["dataset"]["total_observations"] == 40
    assert "performance" in results
    assert "mean_latency_ms" in results["performance"]
    assert "binary_threat_metrics" in results
    assert "multiclass_confusion_matrix" in results
    assert "confidence_distribution" in results

    metrics = results["binary_threat_metrics"]
    assert metrics["precision"] >= 0.90
    assert metrics["recall"] >= 0.90

