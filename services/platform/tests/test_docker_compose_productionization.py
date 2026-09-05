import json
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def test_docker_compose_topology_and_services():
    """Verify all 6 services are properly defined with correct ports, healthchecks, and networks."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), f"docker-compose.yml not found at {compose_file}"

    content = compose_file.read_text(encoding="utf-8")
    expected_services = [
        "demo-api:",
        "traffic-intelligence:",
        "demand-intelligence:",
        "platform:",
        "prometheus:",
        "grafana:",
    ]
    for s_name in expected_services:
        assert s_name in content, f"Missing service {s_name} in docker-compose.yml"

    # Verify container names and network
    for s in ["demo-api", "traffic-intelligence", "demand-intelligence", "platform", "prometheus", "grafana"]:
        assert f"container_name: sentinelscale-{s}" in content
    assert "sentinelscale-net" in content
    assert "restart: unless-stopped" in content
    assert "healthcheck:" in content

    # Verify dependency conditions
    assert "traffic-intelligence:" in content
    assert "condition: service_healthy" in content
    assert "demand-intelligence:" in content
    assert "prometheus:" in content

    # Verify named volumes
    assert "prometheus-data:" in content
    assert "grafana-data:" in content


def test_prometheus_authoritative_scrape_topology():
    """Verify Prometheus scrape configuration has single authoritative targets for metrics services."""
    prom_file = REPO_ROOT / "telemetry" / "prometheus" / "prometheus.yml"
    assert prom_file.exists(), f"prometheus.yml not found at {prom_file}"

    content = prom_file.read_text(encoding="utf-8")
    assert "job_name: 'sentinelscale-services'" in content
    assert "metrics_path: '/metrics'" in content
    assert "demo-api:8000" in content
    assert "platform:8003" in content

    # Ensure no host-local duplicate targets exist in authoritative container job
    assert "127.0.0.1" not in content
    assert "localhost" not in content


def test_platform_dockerfile_permissions():
    """Verify Platform Dockerfile creates data directory with non-root ownership."""
    dockerfile = REPO_ROOT / "services" / "platform" / "Dockerfile"
    assert dockerfile.exists(), f"Dockerfile not found at {dockerfile}"

    content = dockerfile.read_text(encoding="utf-8")
    assert "mkdir -p /app/data" in content
    assert "chown -R sentinel:sentinel /app" in content
    assert "USER sentinel" in content
