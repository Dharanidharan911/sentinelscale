import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import jsonschema
from fastapi.testclient import TestClient
from app.main import app
from tests.fixtures_decision import make_decision_context

client = TestClient(app)

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"


def load_contract_schema(relative_path: str) -> dict:
    with open(CONTRACTS_DIR / relative_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_local_ref_resolver() -> jsonschema.RefResolver:
    """
    Resolve $ref URLs (https://sentinelscale.io/schemas/v1/...) against the
    local contracts/ directory — no network access required.
    """
    schema_files = {
        "traffic_assessment.schema.json": load_contract_schema("traffic/traffic_assessment.schema.json"),
        "demand_forecast.schema.json": load_contract_schema("demand/demand_forecast.schema.json"),
        "resource_state.schema.json": load_contract_schema("resources/resource_state.schema.json"),
        "decision_context.schema.json": load_contract_schema("decisions/decision_context.schema.json"),
        "scaling_decision.schema.json": load_contract_schema("decisions/scaling_decision.schema.json"),
    }

    def resolve(uri: str):
        file_name = uri.rsplit("/", 1)[-1]
        if file_name not in schema_files:
            raise jsonschema.RefResolutionError(f"Unknown contract ref: {uri}")
        return schema_files[file_name]

    class LocalRefResolver(jsonschema.RefResolver):
        def resolve_remote(self, uri: str):
            return resolve(uri)

    return LocalRefResolver(base_uri="", referrer={})


def test_resource_state_matches_json_schema():
    schema_path = Path(__file__).resolve().parents[3] / "contracts" / "resources" / "resource_state.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    response = client.get("/api/v1/resources/current")
    assert response.status_code == 200
    payload = response.json()

    jsonschema.validate(instance=payload, schema=schema)


def test_decision_context_model_matches_json_schema():
    """Verify a typed DecisionContext (built from contract-valid fixtures) conforms to its frozen JSON Schema."""
    resolver = build_local_ref_resolver()
    context = make_decision_context(trace_id="contract-context-trace")

    jsonschema.validate(
        # exclude_none: policy_overrides is optional (absent), not JSON null
        instance=context.model_dump(mode="json", exclude_none=True),
        schema=load_contract_schema("decisions/decision_context.schema.json"),
        resolver=resolver,
    )


def test_scaling_decision_matches_json_schema():
    decision_schema_path = Path(__file__).resolve().parents[3] / "contracts" / "decisions" / "scaling_decision.schema.json"
    with open(decision_schema_path, "r", encoding="utf-8") as f:
        decision_schema = json.load(f)

    context_payload = {
        "context_id": str(uuid.uuid4()),
        "trace_id": "test-trace-contract-123",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "contract_version": "1.0.0",
        "target_workload": "demo-api",
        "traffic_assessment": {
            "event_id": str(uuid.uuid4()),
            "trace_id": "test-trace-contract-123",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "contract_version": "1.0.0",
            "service_version": "0.1.0",
            "model_version": "traffic-v0 (mock)",
            "window_seconds": 60,
            "total_rps": 2500.0,
            "legitimate_rps_estimate": 850.0,
            "suspicious_rps_estimate": 1650.0,
            "risk_score": 0.84,
            "legitimacy_score": 0.34,
            "confidence": 0.91,
            "classification": "suspicious",
            "top_signals": ["high_burst_rate"]
        },
        "demand_forecast": {
            "event_id": str(uuid.uuid4()),
            "trace_id": "test-trace-contract-123",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "contract_version": "1.0.0",
            "service_version": "0.1.0",
            "model_version": "demand-v0 (mock)",
            "forecast_horizon_seconds": 300,
            "predicted_legitimate_rps": 1100.0,
            "lower_bound_rps": 950.0,
            "upper_bound_rps": 1250.0,
            "confidence": 0.91
        },
        "resource_state": {
            "event_id": str(uuid.uuid4()),
            "trace_id": "test-trace-contract-123",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "contract_version": "1.0.0",
            "service_version": "0.1.0",
            "target_namespace": "sentinelscale",
            "target_workload": "demo-api",
            "cpu_utilization": 0.75,
            "memory_utilization": 0.50,
            "cpu_requested_cores": 4.0,
            "cpu_limit_cores": 8.0,
            "memory_requested_bytes": 4294967296,
            "memory_limit_bytes": 8589934592,
            "running_pods": 4,
            "desired_pods": 4,
            "pending_pods": 0,
            "request_rate": 2500.0,
            "p95_latency_ms": 45.0,
            "error_rate": 0.001,
            "current_capacity_rps": 1400.0,
            "estimated_required_capacity_rps": 1200.0,
            "estimated_resource_waste": 0.14
        },
        "dry_run": True,
        "shadow_mode": True
    }

    response = client.post("/api/v1/decision/evaluate", json=context_payload)
    assert response.status_code == 200
    payload = response.json()

    jsonschema.validate(instance=payload, schema=decision_schema)
