import json
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def test_grafana_datasource_provisioning_valid():
    """Verify Grafana Prometheus datasource provisioning file structure."""
    ds_file = REPO_ROOT / "telemetry" / "grafana" / "provisioning" / "datasources" / "prometheus.yaml"
    assert ds_file.exists(), f"Datasource file not found at {ds_file}"

    content = ds_file.read_text(encoding="utf-8")
    assert "type: prometheus" in content
    assert "url: http://prometheus:9090" in content
    assert "isDefault: true" in content


def test_grafana_dashboard_provider_provisioning_valid():
    """Verify Grafana dashboard provider configuration."""
    provider_file = REPO_ROOT / "telemetry" / "grafana" / "provisioning" / "dashboards" / "dashboards.yaml"
    assert provider_file.exists(), f"Provider file not found at {provider_file}"

    content = provider_file.read_text(encoding="utf-8")
    assert "type: file" in content
    assert "path: /var/lib/grafana/dashboards" in content


def test_grafana_infrastructure_dashboard_json_conformance():
    """Verify Grafana dashboard JSON schema, panels, and PromQL queries."""
    dashboard_file = REPO_ROOT / "telemetry" / "grafana" / "dashboards" / "infrastructure_observability.json"
    assert dashboard_file.exists(), f"Dashboard JSON not found at {dashboard_file}"

    raw_json = dashboard_file.read_text(encoding="utf-8")
    dashboard = json.loads(raw_json)

    assert dashboard.get("title") == "SentinelScale — Infrastructure Observability"
    assert dashboard.get("schemaVersion") >= 30
    assert "sentinelscale" in dashboard.get("tags", [])

    panels = dashboard.get("panels", [])
    assert len(panels) >= 8, f"Expected at least 8 panels/rows, found {len(panels)}"

    promql_exprs = []
    panel_titles = []
    for p in panels:
        if p.get("type") == "row":
            continue
        panel_titles.append(p.get("title", ""))
        for target in p.get("targets", []):
            expr = target.get("expr", "").strip()
            assert expr, f"Panel '{p.get('title')}' has empty PromQL expression"
            promql_exprs.append(expr)

    joined_exprs = " ".join(promql_exprs)
    assert "http_requests_total" in joined_exprs
    assert "http_request_duration_seconds" in joined_exprs
    assert "process_cpu_seconds_total" in joined_exprs or "container_cpu_usage_seconds_total" in joined_exprs
    assert "process_resident_memory_bytes" in joined_exprs or "container_memory_working_set_bytes" in joined_exprs
    assert "up" in joined_exprs


def test_docker_compose_includes_grafana_service():
    """Verify docker-compose.yml contains the Grafana service definition."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), f"docker-compose.yml not found at {compose_file}"

    content = compose_file.read_text(encoding="utf-8")
    assert "grafana:" in content
    assert "image: grafana/grafana:10.4.1" in content
    assert ":3000" in content
    assert "prometheus" in content

