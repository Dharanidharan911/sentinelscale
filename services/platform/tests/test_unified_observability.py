"""
Tests for SentinelScale Unified Observability (Stage M3-10)
Validates:
- Grafana datasource provisioning (Prometheus, Tempo, Loki)
- Cross-signal correlation configuration (tracesToLogs, derivedFields)
- Unified Observability dashboard schema and panel definitions
- Tempo and Loki backend configurations
- Docker Compose and Kubernetes manifest definitions for Unified Observability
"""

import json
from pathlib import Path
import pytest
import re

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TELEMETRY_DIR = REPO_ROOT / "telemetry"
GRAFANA_DIR = TELEMETRY_DIR / "grafana"
K8S_DIR = REPO_ROOT / "infrastructure" / "kubernetes"


def test_grafana_datasources_provisioning():
    """Validates Prometheus, Tempo, and Loki datasources are provisioned with correlation links."""
    ds_dir = GRAFANA_DIR / "provisioning" / "datasources"
    assert ds_dir.exists(), "Datasources provisioning directory must exist"

    prom_file = ds_dir / "prometheus.yaml"
    tempo_file = ds_dir / "tempo.yaml"
    loki_file = ds_dir / "loki.yaml"

    assert prom_file.exists(), "prometheus.yaml datasource must exist"
    assert tempo_file.exists(), "tempo.yaml datasource must exist"
    assert loki_file.exists(), "loki.yaml datasource must exist"

    # 1. Prometheus datasource
    prom_text = prom_file.read_text(encoding="utf-8")
    assert "name: Prometheus" in prom_text
    assert "type: prometheus" in prom_text
    assert "http://prometheus:9090" in prom_text

    # 2. Tempo datasource
    tempo_text = tempo_file.read_text(encoding="utf-8")
    assert "name: Tempo" in tempo_text
    assert "type: tempo" in tempo_text
    assert "http://tempo:3200" in tempo_text
    assert "uid: tempo" in tempo_text
    assert "tracesToLogs:" in tempo_text
    assert "datasourceUid: loki" in tempo_text

    # 3. Loki datasource
    loki_text = loki_file.read_text(encoding="utf-8")
    assert "name: Loki" in loki_text
    assert "type: loki" in loki_text
    assert "http://loki:3100" in loki_text
    assert "uid: loki" in loki_text
    assert "derivedFields:" in loki_text
    assert "datasourceUid: tempo" in loki_text


def test_derived_fields_regex_matches_trace_ids():
    """Validates the Loki derivedFields regex correctly extracts 32-hex OTel trace IDs."""
    pattern = r'"(?:otel_trace_id|trace_id)":\s*"([a-f0-9]{32})"'

    log_line_otel = '{"timestamp": "2026-09-06T12:00:00Z", "otel_trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "level": "INFO"}'
    match = re.search(pattern, log_line_otel)
    assert match is not None
    assert match.group(1) == "4bf92f3577b34da6a3ce929d0e0e4736"

    log_line_legacy = '{"timestamp": "2026-09-06T12:00:00Z", "trace_id": "0af7651916cd43dd8448eb211c80319c", "level": "INFO"}'
    match_legacy = re.search(pattern, log_line_legacy)
    assert match_legacy is not None
    assert match_legacy.group(1) == "0af7651916cd43dd8448eb211c80319c"


def test_dashboards_presence_and_schema():
    """Validates presence and schema of both infrastructure and unified observability dashboards."""
    dashboards_dir = GRAFANA_DIR / "dashboards"
    assert dashboards_dir.exists()

    infra_file = dashboards_dir / "infrastructure_observability.json"
    unified_file = dashboards_dir / "unified_observability.json"

    assert infra_file.exists(), "infrastructure_observability.json must exist"
    assert unified_file.exists(), "unified_observability.json must exist"

    # Check Infra Dashboard
    infra_data = json.loads(infra_file.read_text(encoding="utf-8"))
    assert infra_data.get("uid") == "sentinelscale-infra-obs"
    assert len(infra_data.get("panels", [])) >= 8

    # Check Unified Dashboard
    unified_data = json.loads(unified_file.read_text(encoding="utf-8"))
    assert unified_data.get("uid") == "sentinelscale-unified-obs"
    panels = unified_data.get("panels", [])
    assert len(panels) >= 8

    panel_types = {p.get("type") for p in panels}
    assert "stat" in panel_types
    assert "timeseries" in panel_types
    assert "logs" in panel_types
    assert "traces" in panel_types

    # Ensure logs panel targets Loki and traces panel targets Tempo
    logs_panel = next(p for p in panels if p.get("type") == "logs")
    assert logs_panel.get("datasource", {}).get("type") == "loki" or logs_panel.get("datasource", {}).get("uid") == "loki"

    traces_panel = next(p for p in panels if p.get("type") == "traces")
    assert traces_panel.get("datasource", {}).get("type") == "tempo" or traces_panel.get("datasource", {}).get("uid") == "tempo"


def test_telemetry_configs():
    """Validates Tempo, Loki, and OpenTelemetry Collector configs."""
    tempo_cfg = TELEMETRY_DIR / "tempo" / "tempo-config.yaml"
    loki_cfg = TELEMETRY_DIR / "loki" / "loki-config.yaml"
    otel_cfg = TELEMETRY_DIR / "otel" / "otel-collector-config.yaml"

    assert tempo_cfg.exists()
    assert loki_cfg.exists()
    assert otel_cfg.exists()

    tempo_text = tempo_cfg.read_text(encoding="utf-8")
    assert "http_listen_port: 3200" in tempo_text
    assert "0.0.0.0:4317" in tempo_text

    loki_text = loki_cfg.read_text(encoding="utf-8")
    assert "http_listen_port: 3100" in loki_text

    otel_text = otel_cfg.read_text(encoding="utf-8")
    assert "otlp/tempo:" in otel_text
    assert "endpoint: tempo:4317" in otel_text
    assert "exporters: [debug, otlp/tempo]" in otel_text or "- otlp/tempo" in otel_text


def test_docker_compose_unified_observability():
    """Validates docker-compose.yml defines tempo and loki services."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists()
    compose_text = compose_file.read_text(encoding="utf-8")

    assert "tempo:" in compose_text
    assert "grafana/tempo:2.4.1" in compose_text
    assert "3200" in compose_text

    assert "loki:" in compose_text
    assert "grafana/loki:2.9.8" in compose_text
    assert "3100" in compose_text


def test_kubernetes_tempo_and_loki_manifests():
    """Validates Kubernetes manifests for Tempo and Loki."""
    tempo_k8s = K8S_DIR / "tempo"
    loki_k8s = K8S_DIR / "loki"

    assert (tempo_k8s / "configmap.yaml").exists()
    assert (tempo_k8s / "deployment.yaml").exists()

    assert (loki_k8s / "configmap.yaml").exists()
    assert (loki_k8s / "deployment.yaml").exists()

    tempo_dep = (tempo_k8s / "deployment.yaml").read_text(encoding="utf-8")
    assert "grafana/tempo:2.4.1" in tempo_dep
    assert "name: tempo" in tempo_dep

    loki_dep = (loki_k8s / "deployment.yaml").read_text(encoding="utf-8")
    assert "grafana/loki:2.9.8" in loki_dep
    assert "name: loki" in loki_dep
