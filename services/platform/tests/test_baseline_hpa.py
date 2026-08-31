import uuid
from datetime import datetime, timezone
from app.models.resource import ResourceState
from app.services.baseline_hpa import BaselineHPACalculator


def test_baseline_hpa_calculation():
    calc = BaselineHPACalculator(target_cpu_utilization=0.70, min_pods=2, max_pods=10)
    resource_state = ResourceState(
        event_id=str(uuid.uuid4()),
        trace_id="trace-test",
        timestamp=datetime.now(timezone.utc).isoformat(),
        contract_version="1.0.0",
        service_version="0.1.0",
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=0.90,  # 90% CPU vs 70% target -> 4 * (0.90/0.70) = 5.14 -> 6 pods
        memory_utilization=0.50,
        cpu_requested_cores=4.0,
        cpu_limit_cores=8.0,
        memory_requested_bytes=4294967296,
        memory_limit_bytes=8589934592,
        running_pods=4,
        desired_pods=4,
        pending_pods=0,
        request_rate=2500.0,
        p95_latency_ms=45.0,
        error_rate=0.001,
        current_capacity_rps=1400.0,
        estimated_required_capacity_rps=1200.0,
        estimated_resource_waste=0.14
    )

    baseline_pods = calc.calculate_baseline_replicas(resource_state)
    assert baseline_pods == 6


def test_baseline_hpa_clamps_to_min_and_max():
    calc = BaselineHPACalculator(target_cpu_utilization=0.70, min_pods=3, max_pods=5)
    low_load_state = ResourceState(
        event_id=str(uuid.uuid4()),
        trace_id="trace-test",
        timestamp=datetime.now(timezone.utc).isoformat(),
        contract_version="1.0.0",
        service_version="0.1.0",
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=0.10,
        memory_utilization=0.20,
        cpu_requested_cores=4.0,
        cpu_limit_cores=8.0,
        memory_requested_bytes=4294967296,
        memory_limit_bytes=8589934592,
        running_pods=4,
        desired_pods=4,
        pending_pods=0,
        request_rate=100.0,
        p95_latency_ms=10.0,
        error_rate=0.0,
        current_capacity_rps=1400.0,
        estimated_required_capacity_rps=200.0,
        estimated_resource_waste=0.85
    )

    # Clamped to min_pods = 3
    assert calc.calculate_baseline_replicas(low_load_state) == 3
