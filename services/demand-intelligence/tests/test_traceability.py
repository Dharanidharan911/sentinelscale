"""
SentinelScale — Demand Intelligence — Test: Traceability
Verifies trace ID propagation and event metadata invariants.
"""
import uuid
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestTraceability:
    def _make_observations(self, n: int = 10):
        return [
            {"timestamp": 1_700_000_000.0 + i * 30, "rps": 500.0}
            for i in range(n)
        ]

    def test_trace_id_propagated_from_request_body(self):
        payload = {
            "forecast_horizon_seconds": 300,
            "trace_id": "my-upstream-trace-abc",
            "observations": self._make_observations(),
        }
        response = client.post("/api/v1/demand/forecast", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["trace_id"] == "my-upstream-trace-abc"

    def test_trace_id_propagated_from_header(self):
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": self._make_observations(),
        }
        response = client.post(
            "/api/v1/demand/forecast",
            json=payload,
            headers={"X-Trace-ID": "header-trace-xyz"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["trace_id"] == "header-trace-xyz"

    def test_trace_id_body_takes_precedence_over_header(self):
        payload = {
            "forecast_horizon_seconds": 300,
            "trace_id": "body-trace",
            "observations": self._make_observations(),
        }
        response = client.post(
            "/api/v1/demand/forecast",
            json=payload,
            headers={"X-Trace-ID": "header-trace"},
        )
        assert response.status_code == 200
        assert response.json()["trace_id"] == "body-trace"

    def test_trace_id_auto_generated_when_absent(self):
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": self._make_observations(),
        }
        response = client.post("/api/v1/demand/forecast", json=payload)
        assert response.status_code == 200
        trace_id = response.json()["trace_id"]
        assert isinstance(trace_id, str)
        assert len(trace_id) > 0

    def test_event_id_is_valid_uuid(self):
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": self._make_observations(),
        }
        response = client.post("/api/v1/demand/forecast", json=payload)
        assert response.status_code == 200
        event_id = response.json()["event_id"]
        # Must parse as a valid UUID4
        parsed = uuid.UUID(event_id)
        assert str(parsed) == event_id

    def test_event_id_unique_per_call(self):
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": self._make_observations(),
        }
        r1 = client.post("/api/v1/demand/forecast", json=payload)
        r2 = client.post("/api/v1/demand/forecast", json=payload)
        assert r1.json()["event_id"] != r2.json()["event_id"]

    def test_generated_at_is_valid_iso8601(self):
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": self._make_observations(),
        }
        response = client.post("/api/v1/demand/forecast", json=payload)
        assert response.status_code == 200
        generated_at = response.json()["generated_at"]
        # Must parse without raising
        dt = datetime.fromisoformat(generated_at)
        assert dt is not None

    def test_contract_version_is_1_0_0(self):
        payload = {
            "forecast_horizon_seconds": 300,
            "observations": self._make_observations(),
        }
        response = client.post("/api/v1/demand/forecast", json=payload)
        assert response.status_code == 200
        assert response.json()["contract_version"] == "1.0.0"
