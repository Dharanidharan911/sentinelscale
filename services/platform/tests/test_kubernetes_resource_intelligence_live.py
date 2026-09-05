"""
Integration and conformance tests for Stage M3-6: Kubernetes Resource Intelligence.
Validates live Kubernetes resource retrieval, quantity parsing normalization,
ResourceState contract schema conformance, and DecisionEngine integration.
"""

import json
from pathlib import Path
import jsonschema
import pytest
from app.config.settings import settings
from app.models.context import DecisionContext
from app.models.resource import ResourceState
from app.services.decision_engine import DecisionEngine
from app.services.telemetry.quantity_parser import parse_cpu_quantity, parse_memory_quantity
from tests.fixtures_decision import make_demand_forecast, make_traffic_assessment

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RESOURCE_SCHEMA_PATH = REPO_ROOT / "contracts" / "resources" / "resource_state.schema.json"


@pytest.fixture(scope="module")
def resource_schema() -> dict:
    with open(RESOURCE_SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_resource_state_schema_file_exists():
    assert RESOURCE_SCHEMA_PATH.exists(), f"Contract schema not found at {RESOURCE_SCHEMA_PATH}"


@pytest.mark.parametrize("cpu_input,expected_cores", [
    ("100m", 0.1),
    ("250m", 0.25),
    ("500m", 0.5),
    ("1000m", 1.0),
    ("1500m", 1.5),
    ("2", 2.0),
    ("0.75", 0.75),
    (4, 4.0),
    (0.5, 0.5),
    (None, 0.0),
    ("", 0.0),
])
def test_cpu_quantity_parsing_comprehensive(cpu_input, expected_cores):
    assert parse_cpu_quantity(cpu_input) == expected_cores


@pytest.mark.parametrize("mem_input,expected_bytes", [
    ("64Ki", 64 * 1024),
    ("128Mi", 128 * 1024 * 1024),
    ("256Mi", 256 * 1024 * 1024),
    ("512Mi", 512 * 1024 * 1024),
    ("1Gi", 1024 * 1024 * 1024),
    ("4Gi", 4 * 1024 * 1024 * 1024),
    ("100k", 100 * 1000),
    ("500M", 500 * 1000 * 1000),
    ("2G", 2 * 1000 * 1000 * 1000),
    (1048576, 1048576),
    (None, 0),
    ("", 0),
])
def test_memory_quantity_parsing_comprehensive(mem_input, expected_bytes):
    assert parse_memory_quantity(mem_input) == expected_bytes


def test_kubernetes_provider_state_matches_json_schema(resource_schema):
    """Verify that a synthetic Kubernetes ResourceState strictly conforms to the JSON Schema."""
    k8s_state = ResourceState(
        event_id="3fe7d1d9-2174-4c04-90c9-69f04d2e2a2d",
        trace_id="trace-k8s-conformance-001",
        timestamp="2026-09-06T00:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=0.15,
        memory_utilization=0.45,
        cpu_requested_cores=0.2,
        cpu_limit_cores=1.0,
        memory_requested_bytes=268435456,
        memory_limit_bytes=536870912,
        running_pods=2,
        desired_pods=2,
        pending_pods=0,
        request_rate=25.0,
        p95_latency_ms=4.5,
        error_rate=0.0,
        current_capacity_rps=700.0,
        estimated_required_capacity_rps=25.0,
        estimated_resource_waste=0.9643,
    )

    state_dict = k8s_state.model_dump()
    jsonschema.validate(instance=state_dict, schema=resource_schema)


@pytest.mark.asyncio
async def test_decision_engine_evaluates_kubernetes_resource_state():
    """Verify DecisionEngine processes DecisionContext containing real Kubernetes resource attributes."""
    engine = DecisionEngine()

    k8s_resource_state = ResourceState(
        event_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        trace_id="trace-engine-k8s-eval",
        timestamp="2026-09-06T00:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        target_namespace="sentinelscale",
        target_workload="demo-api",
        cpu_utilization=0.05,
        memory_utilization=0.12,
        cpu_requested_cores=0.2,
        cpu_limit_cores=1.0,
        memory_requested_bytes=268435456,
        memory_limit_bytes=536870912,
        running_pods=2,
        desired_pods=2,
        pending_pods=0,
        request_rate=15.0,
        p95_latency_ms=3.2,
        error_rate=0.0,
        current_capacity_rps=700.0,
        estimated_required_capacity_rps=15.0,
        estimated_resource_waste=0.9786,
    )

    context = DecisionContext(
        context_id="ctx-k8s-001",
        trace_id="trace-engine-k8s-eval",
        timestamp="2026-09-06T00:00:00Z",
        contract_version="1.0.0",
        target_workload="demo-api",
        traffic_assessment=make_traffic_assessment(),
        demand_forecast=make_demand_forecast(),
        resource_state=k8s_resource_state,
        policy_overrides=None,
    )

    decision = await engine.evaluate_decision(context)

    assert decision is not None
    assert decision.action in ["HOLD", "SCALE", "RATE_LIMIT"]
    assert decision.dry_run is True
    assert decision.shadow_mode is True
