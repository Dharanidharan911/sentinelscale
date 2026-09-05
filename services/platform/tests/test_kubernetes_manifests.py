"""
Unit tests for SentinelScale Stage M3-5 Kubernetes Manifests and RBAC definitions.
Validates YAML file presence, namespace scoping, security contexts, probes, labels, and safety guardrails.
"""

from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
K8S_DIR = REPO_ROOT / "infrastructure" / "kubernetes"


def test_namespace_manifest():
    ns_file = K8S_DIR / "namespace.yaml"
    assert ns_file.exists(), "namespace.yaml must exist"
    content = ns_file.read_text(encoding="utf-8")
    assert "kind: Namespace" in content
    assert "name: sentinelscale" in content


def test_rbac_manifest_is_strictly_read_only():
    rbac_file = K8S_DIR / "platform" / "rbac.yaml"
    assert rbac_file.exists(), "platform rbac.yaml must exist"
    content = rbac_file.read_text(encoding="utf-8")

    assert "kind: ServiceAccount" in content
    assert "name: sentinelscale-platform" in content
    assert "kind: Role" in content
    assert "name: sentinelscale-platform-reader" in content
    assert "kind: RoleBinding" in content
    assert "name: sentinelscale-platform-reader-binding" in content

    # Verbs must be strictly read-only
    assert '"get"' in content or "- get" in content or "get" in content
    assert '"list"' in content or "- list" in content or "list" in content
    for forbidden_verb in ["create", "update", "patch", "delete", "deletecollection", "*"]:
        # Verify forbidden verb is not in rules
        lines = [line.strip() for line in content.splitlines()]
        verbs_lines = [l for l in lines if "verbs:" in l or (l.startswith("-") and forbidden_verb in l)]
        for vl in verbs_lines:
            assert forbidden_verb not in vl, f"Forbidden verb {forbidden_verb} found in RBAC: {vl}"


@pytest.mark.parametrize("service_name,port", [
    ("demo-api", 8000),
    ("traffic-intelligence", 8001),
    ("demand-intelligence", 8002),
    ("platform", 8003),
])
def test_application_deployments_and_services(service_name, port):
    svc_dir = K8S_DIR / service_name
    deploy_file = svc_dir / "deployment.yaml"
    service_file = svc_dir / "service.yaml"

    assert deploy_file.exists(), f"Deployment manifest for {service_name} must exist"
    assert service_file.exists(), f"Service manifest for {service_name} must exist"

    deploy_content = deploy_file.read_text(encoding="utf-8")
    service_content = service_file.read_text(encoding="utf-8")

    # Namespace & service name
    assert "namespace: sentinelscale" in deploy_content
    assert "namespace: sentinelscale" in service_content
    assert f"name: {service_name}" in deploy_content
    assert f"name: {service_name}" in service_content

    # Security context & probes
    assert "runAsNonRoot: true" in deploy_content
    assert "imagePullPolicy: IfNotPresent" in deploy_content
    assert f"containerPort: {port}" in deploy_content
    assert "livenessProbe:" in deploy_content
    assert "readinessProbe:" in deploy_content

    # Service configuration
    assert "type: ClusterIP" in service_content
    assert f"port: {port}" in service_content


def test_platform_deployment_safety_and_discovery_env():
    deploy_file = K8S_DIR / "platform" / "deployment.yaml"
    content = deploy_file.read_text(encoding="utf-8")

    # Service Account
    assert "serviceAccountName: sentinelscale-platform" in content

    # Service Discovery URLs
    assert "traffic-intelligence" in content
    assert "demand-intelligence" in content
    assert "prometheus" in content

    # Safety Invariants
    assert 'name: SENTINEL_DRY_RUN\n              value: "true"' in content or 'SENTINEL_DRY_RUN' in content
    assert 'name: SENTINEL_SHADOW_MODE\n              value: "true"' in content or 'SENTINEL_SHADOW_MODE' in content
    assert 'name: SENTINEL_AUTONOMOUS_ACTIONS_ENABLED\n              value: "false"' in content or 'SENTINEL_AUTONOMOUS_ACTIONS_ENABLED' in content


def test_prometheus_and_grafana_manifests():
    prom_cm = K8S_DIR / "prometheus" / "configmap.yaml"
    prom_deploy = K8S_DIR / "prometheus" / "deployment.yaml"
    prom_svc = K8S_DIR / "prometheus" / "service.yaml"

    assert prom_cm.exists()
    assert prom_deploy.exists()
    assert prom_svc.exists()

    prom_cm_content = prom_cm.read_text(encoding="utf-8")
    assert "demo-api" in prom_cm_content
    assert "platform" in prom_cm_content
    assert ":8000" in prom_cm_content
    assert ":8003" in prom_cm_content

    grafana_cm = K8S_DIR / "grafana" / "configmaps.yaml"
    grafana_deploy = K8S_DIR / "grafana" / "deployment.yaml"
    grafana_svc = K8S_DIR / "grafana" / "service.yaml"

    assert grafana_cm.exists()
    assert grafana_deploy.exists()
    assert grafana_svc.exists()
