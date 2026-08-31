import json
from pathlib import Path
import jsonschema
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_traffic_assessment_matches_json_schema():
    # Load JSON schema contract
    schema_path = Path(__file__).resolve().parents[3] / "contracts" / "traffic" / "traffic_assessment.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    # Fetch assessment response
    response = client.post("/api/v1/traffic/assess", json={"window_seconds": 60})
    assert response.status_code == 200
    payload = response.json()

    # Validate against JSON Schema
    jsonschema.validate(instance=payload, schema=schema)
