"""
Unit tests for SentinelScale Stage M3-7 Real Kubernetes HPA and RBAC definitions.
Validates HPA manifest structure, autoscaling/v2 API, target workload reference,
bounds (min 2, max 5), CPU metric target (50%), stabilization window, and RBAC permissions.
"""

from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
K8S_DIR = REPO_ROOT / "infrastructure" / "kubernetes"


def test_demo_api_hpa_manifest_exists():
    hpa_file = K8S_DIR / "demo-api" / "hpa.yaml"
    assert hpa_file.exists(), "demo-api/hpa.yaml manifest must exist"


def test_demo_api_hpa_structure_and_constraints():
    hpa_file = K8S_DIR / "demo-api" / "hpa.yaml"
    content = hpa_file.read_text(encoding="utf-8")

    assert "apiVersion: autoscaling/v2" in content, "Must use modern autoscaling/v2 API"
    assert "kind: HorizontalPodAutoscaler" in content
    assert "name: demo-api-hpa" in content
    assert "namespace: sentinelscale" in content

    # Workload target
    assert "kind: Deployment" in content
    assert "name: demo-api" in content

    # Replica bounds
    assert "minReplicas: 2" in content, "HPA minReplicas must be 2"
    assert "maxReplicas: 5" in content, "HPA maxReplicas must be 5"

    # CPU Metric target
    assert "type: Resource" in content
    assert "name: cpu" in content
    assert "averageUtilization: 50" in content, "Target CPU utilization must be 50%"

    # Behavior policies
    assert "scaleUp:" in content
    assert "scaleDown:" in content
    assert "stabilizationWindowSeconds: 15" in content, "Scale down stabilization window should be 15s"


def test_platform_rbac_includes_hpa_read_only():
    rbac_file = K8S_DIR / "platform" / "rbac.yaml"
    assert rbac_file.exists(), "platform/rbac.yaml must exist"
    content = rbac_file.read_text(encoding="utf-8")

    # Check that horizontalpodautoscalers is listed under autoscaling apiGroups
    assert "horizontalpodautoscalers" in content
    assert "autoscaling" in content
    assert "get" in content
    assert "list" in content

    # Ensure no mutation verbs are assigned in RBAC
    lines = [l.strip() for l in content.splitlines()]
    for forbidden in ["create", "update", "patch", "delete", "deletecollection", "*"]:
        verb_lines = [l for l in lines if f'- "{forbidden}"' in l or f"- '{forbidden}'" in l or f"- {forbidden}" in l]
        assert len(verb_lines) == 0, f"Forbidden verb {forbidden} found in RBAC"
