import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "control-center"


def test_ready_endpoint():
    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"


def test_version_endpoint():
    resp = client.get("/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "control-center"
    assert "service_version" in data
    assert "platform_url" in data


def test_static_index_page():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SENTINEL" in resp.text
    assert "Control Center" in resp.text
    assert "SAFETY STATUS &amp; INVARIANTS" in resp.text or "SAFETY STATUS" in resp.text
    assert "70% CPU" in resp.text
    assert "350.0 RPS / Pod" in resp.text

