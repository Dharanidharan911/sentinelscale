"""Unit and integration validation tests for SentinelScale Stage M3-4 k6 Load Testing."""

import json
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def test_k6_script_files_exist_and_structure_valid():
    """Verify presence and structure of k6 load testing scripts."""
    k6_dir = REPO_ROOT / "load-tests" / "k6"
    assert k6_dir.exists() and k6_dir.is_dir(), f"k6 directory missing at {k6_dir}"

    workload_file = k6_dir / "workload.js"
    endpoints_file = k6_dir / "endpoints.js"
    profiles_file = k6_dir / "profiles.js"

    assert workload_file.exists(), f"Missing {workload_file}"
    assert endpoints_file.exists(), f"Missing {endpoints_file}"
    assert profiles_file.exists(), f"Missing {profiles_file}"

    # Verify endpoints coverage
    endpoints_content = endpoints_file.read_text(encoding="utf-8")
    assert "export function listProducts" in endpoints_content
    assert "export function getProduct" in endpoints_content
    assert "export function searchProducts" in endpoints_content
    assert "export function loginUser" in endpoints_content
    assert "export function updateCart" in endpoints_content
    assert "export function checkout" in endpoints_content
    assert "export function checkHealth" in endpoints_content

    # Verify profiles coverage
    profiles_content = profiles_file.read_text(encoding="utf-8")
    assert "smoke:" in profiles_content
    assert "baseline:" in profiles_content
    assert "spike:" in profiles_content
    assert "sustained:" in profiles_content
    assert "VU_SCALE" in profiles_content
    assert "DURATION_SCALE" in profiles_content

    # Verify workload master script
    workload_content = workload_file.read_text(encoding="utf-8")
    assert "TARGET_URL" in workload_content
    assert "PROFILE" in workload_content
    assert "export const options" in workload_content
    assert "export default function" in workload_content


def test_docker_compose_k6_profile_configuration():
    """Verify docker-compose.yml defines the k6 service under the load-test profile."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), f"docker-compose.yml not found at {compose_file}"

    content = compose_file.read_text(encoding="utf-8")
    assert "k6:" in content
    assert "image: grafana/k6:0.50.0" in content
    assert "profiles:" in content
    assert "load-test" in content
    assert "./load-tests/k6:/scripts:ro" in content
    assert "TARGET_URL=${TARGET_URL:-http://demo-api:8000}" in content


def test_load_tests_readme_documentation():
    """Verify load-tests/README.md documents all k6 execution instructions."""
    readme_file = REPO_ROOT / "load-tests" / "README.md"
    assert readme_file.exists(), f"README not found at {readme_file}"

    content = readme_file.read_text(encoding="utf-8")
    assert "k6" in content
    assert "baseline" in content
    assert "spike" in content
    assert "sustained" in content
