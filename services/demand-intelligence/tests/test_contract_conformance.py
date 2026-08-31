import json
from pathlib import Path
import jsonschema
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_demand_forecast_matches_json_schema():
    schema_path = Path(__file__).resolve().parents[3] / "contracts" / "demand" / "demand_forecast.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    response = client.post("/api/v1/demand/forecast", json={"forecast_horizon_seconds": 300})
    assert response.status_code == 200
    payload = response.json()

    jsonschema.validate(instance=payload, schema=schema)
