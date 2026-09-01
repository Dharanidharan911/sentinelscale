import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
import jsonschema
import pytest
from app.models.resource import ResourceState
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.factory import get_telemetry_provider
from app.services.telemetry.kubernetes_provider import KubernetesTelemetryProvider
from app.services.telemetry.quantity_parser import parse_cpu_quantity, parse_memory_quantity


def create_mock_k8s_transport(endpoint_responses: Dict[str, dict]):
    """Creates a mock httpx.AsyncClient that responds to Kubernetes REST API endpoints."""
    async def handler(request: httpx.Request):
        url_path = request.url.path
        query_param = str(request.url.params)

        for pattern, response_data in endpoint_responses.items():
            if pattern in url_path or pattern in query_param or pattern == "*":
                status = response_data.get("status_code", 200)
                body = response_data.get("body", {})
                if isinstance(body, str):
                    return httpx.Response(status_code=status, text=body)
                return httpx.Response(status_code=status, json=body)

        return httpx.Response(status_code=404, json={"message": "Resource not found"})

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="http://mock-k8s:8001")


def test_kubernetes_provider_implements_interface():
    """Verify KubernetesTelemetryProvider implements ResourceTelemetryProvider."""
    provider = KubernetesTelemetryProvider()
    assert isinstance(provider, ResourceTelemetryProvider)
    assert provider.provider_name == "kubernetes"


def test_factory_returns_kubernetes_provider():
    """Verify factory returns KubernetesTelemetryProvider when requested."""
    provider = get_telemetry_provider("kubernetes")
    assert isinstance(provider, KubernetesTelemetryProvider)
    assert provider.provider_name == "kubernetes"


# =========================================================================
# QUANTITY PARSER TESTS
# =========================================================================

def test_parse_cpu_quantity_valid_formats():
    """Verify parsing valid Kubernetes CPU quantity formats into float cores."""
    assert parse_cpu_quantity("100m") == 0.1
    assert parse_cpu_quantity("500m") == 0.5
    assert parse_cpu_quantity("1500m") == 1.5
    assert parse_cpu_quantity("1") == 1.0
    assert parse_cpu_quantity("2") == 2.0
    assert parse_cpu_quantity("0.25") == 0.25
    assert parse_cpu_quantity(4) == 4.0
    assert parse_cpu_quantity(0.5) == 0.5
    assert parse_cpu_quantity(None) == 0.0
    assert parse_cpu_quantity("") == 0.0


def test_parse_cpu_quantity_malformed_formats():
    """Verify malformed or negative CPU quantities raise TelemetryProviderError."""
    with pytest.raises(TelemetryProviderError):
        parse_cpu_quantity("invalid_cpu")

    with pytest.raises(TelemetryProviderError):
        parse_cpu_quantity("-100m")

    with pytest.raises(TelemetryProviderError):
        parse_cpu_quantity("500x")


def test_parse_memory_quantity_valid_formats():
    """Verify parsing valid Kubernetes binary and decimal memory quantities into integer bytes."""
    # Binary SI (powers of 1024)
    assert parse_memory_quantity("128Ki") == 128 * 1024
    assert parse_memory_quantity("256Mi") == 256 * 1024 * 1024
    assert parse_memory_quantity("4Gi") == 4 * 1024 * 1024 * 1024
    assert parse_memory_quantity("1Ti") == 1 * 1024 ** 4

    # Decimal SI (powers of 1000)
    assert parse_memory_quantity("500k") == 500 * 1000
    assert parse_memory_quantity("200M") == 200 * 1000 * 1000
    assert parse_memory_quantity("2G") == 2 * 1000 * 1000 * 1000

    # Plain integers and direct numbers
    assert parse_memory_quantity("1048576") == 1048576
    assert parse_memory_quantity(1048576) == 1048576
    assert parse_memory_quantity(None) == 0
    assert parse_memory_quantity("") == 0


def test_parse_memory_quantity_malformed_formats():
    """Verify malformed or negative memory quantities raise TelemetryProviderError."""
    with pytest.raises(TelemetryProviderError):
        parse_memory_quantity("invalid_mem")

    with pytest.raises(TelemetryProviderError):
        parse_memory_quantity("-256Mi")

    with pytest.raises(TelemetryProviderError):
        parse_memory_quantity("256X")


# =========================================================================
# KUBERNETES PROVIDER WORKLOAD OBSERVATION TESTS
# =========================================================================

@pytest.mark.asyncio
async def test_successful_deployment_and_pod_observation():
    """Verify full observation of Deployment and Pods produces schema-compliant ResourceState."""
    mock_deployment = {
        "metadata": {"name": "demo-api", "namespace": "sentinelscale"},
        "spec": {
            "replicas": 3,
            "selector": {"matchLabels": {"app.kubernetes.io/name": "demo-api"}},
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "demo-api",
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "500m", "memory": "256Mi"}
                            }
                        }
                    ]
                }
            }
        }
    }

    mock_pods = {
        "items": [
            {
                "metadata": {"name": "demo-api-pod-1"},
                "status": {"phase": "Running"},
                "spec": {
                    "containers": [
                        {
                            "name": "demo-api",
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "500m", "memory": "256Mi"}
                            }
                        }
                    ]
                }
            },
            {
                "metadata": {"name": "demo-api-pod-2"},
                "status": {"phase": "Running"},
                "spec": {
                    "containers": [
                        {
                            "name": "demo-api",
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "500m", "memory": "256Mi"}
                            }
                        }
                    ]
                }
            },
            {
                "metadata": {"name": "demo-api-pod-3"},
                "status": {"phase": "Pending"},
                "spec": {
                    "containers": [
                        {
                            "name": "demo-api",
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "500m", "memory": "256Mi"}
                            }
                        }
                    ]
                }
            }
        ]
    }

    mock_responses = {
        "/apis/apps/v1/namespaces/sentinelscale/deployments/demo-api": {
            "status_code": 200,
            "body": mock_deployment
        },
        "/api/v1/namespaces/sentinelscale/pods": {
            "status_code": 200,
            "body": mock_pods
        }
    }

    client = create_mock_k8s_transport(mock_responses)
    provider = KubernetesTelemetryProvider(http_client=client)

    state = await provider.fetch_resource_state(
        namespace="sentinelscale",
        workload="demo-api",
        trace_id="test-k8s-trace-1"
    )

    assert isinstance(state, ResourceState)
    assert state.target_namespace == "sentinelscale"
    assert state.target_workload == "demo-api"
    assert state.trace_id == "test-k8s-trace-1"
    assert state.desired_pods == 3
    assert state.running_pods == 2
    assert state.pending_pods == 1

    # 2 running pods * 0.1 cpu request = 0.2 cores
    assert state.cpu_requested_cores == 0.2
    # 2 running pods * 0.5 cpu limit = 1.0 cores
    assert state.cpu_limit_cores == 1.0
    # 2 running pods * 128Mi = 268435456 bytes
    assert state.memory_requested_bytes == 2 * 128 * 1024 * 1024
    # 2 running pods * 256Mi = 536870912 bytes
    assert state.memory_limit_bytes == 2 * 256 * 1024 * 1024

    # Capacity derived from running pods (2 * 350 = 700 RPS)
    assert state.current_capacity_rps == 700.0

    # JSON Schema Validation
    schema_path = Path(__file__).resolve().parents[3] / "contracts" / "resources" / "resource_state.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(instance=state.model_dump(), schema=schema)


@pytest.mark.asyncio
async def test_multi_container_pod_aggregation():
    """Verify multiple containers in a single pod spec are aggregated correctly."""
    mock_deployment = {
        "metadata": {"name": "demo-api"},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "demo-api"}}
        }
    }
    mock_pods = {
        "items": [
            {
                "status": {"phase": "Running"},
                "spec": {
                    "containers": [
                        {
                            "name": "app",
                            "resources": {
                                "requests": {"cpu": "200m", "memory": "256Mi"},
                                "limits": {"cpu": "1", "memory": "512Mi"}
                            }
                        },
                        {
                            "name": "sidecar",
                            "resources": {
                                "requests": {"cpu": "50m", "memory": "64Mi"},
                                "limits": {"cpu": "100m", "memory": "128Mi"}
                            }
                        }
                    ]
                }
            }
        ]
    }
    mock_responses = {
        "deployments/demo-api": {"status_code": 200, "body": mock_deployment},
        "pods": {"status_code": 200, "body": mock_pods}
    }
    client = create_mock_k8s_transport(mock_responses)
    provider = KubernetesTelemetryProvider(http_client=client)

    state = await provider.fetch_resource_state(namespace="sentinelscale", workload="demo-api")

    assert state.running_pods == 1
    # 0.2 + 0.05 = 0.25 cores
    assert state.cpu_requested_cores == 0.25
    # 1.0 + 0.1 = 1.1 cores
    assert state.cpu_limit_cores == 1.1
    # 256Mi + 64Mi = 320Mi bytes
    assert state.memory_requested_bytes == (256 + 64) * 1024 * 1024
    # 512Mi + 128Mi = 640Mi bytes
    assert state.memory_limit_bytes == (512 + 128) * 1024 * 1024


@pytest.mark.asyncio
async def test_failed_and_succeeded_pods_are_not_counted_as_running():
    """Verify Failed or Succeeded pods are ignored from running pod counts."""
    mock_deployment = {
        "spec": {"replicas": 2, "selector": {"matchLabels": {"app": "demo-api"}}}
    }
    mock_pods = {
        "items": [
            {"status": {"phase": "Running"}, "spec": {"containers": []}},
            {"status": {"phase": "Failed"}, "spec": {"containers": []}},
            {"status": {"phase": "Succeeded"}, "spec": {"containers": []}},
            {"status": {"phase": "Unknown"}, "spec": {"containers": []}},
        ]
    }
    mock_responses = {
        "deployments/demo-api": {"status_code": 200, "body": mock_deployment},
        "pods": {"status_code": 200, "body": mock_pods}
    }
    client = create_mock_k8s_transport(mock_responses)
    provider = KubernetesTelemetryProvider(http_client=client)

    state = await provider.fetch_resource_state(namespace="sentinelscale", workload="demo-api")
    assert state.running_pods == 1
    assert state.pending_pods == 0


@pytest.mark.asyncio
async def test_deployment_404_raises_telemetry_provider_error():
    """Verify 404 on Deployment lookup raises TelemetryProviderError."""
    mock_responses = {
        "*": {"status_code": 404, "body": {"message": "deployment not found"}}
    }
    client = create_mock_k8s_transport(mock_responses)
    provider = KubernetesTelemetryProvider(http_client=client)

    with pytest.raises(TelemetryProviderError) as exc_info:
        await provider.fetch_resource_state(namespace="sentinelscale", workload="non_existent")

    assert "not found" in str(exc_info.value)
    assert exc_info.value.provider_name == "kubernetes"


@pytest.mark.asyncio
async def test_kubernetes_403_forbidden_raises_telemetry_provider_error():
    """Verify 403 Forbidden raises TelemetryProviderError with authorization message."""
    mock_responses = {
        "*": {"status_code": 403, "body": {"message": "User cannot get deployments"}}
    }
    client = create_mock_k8s_transport(mock_responses)
    provider = KubernetesTelemetryProvider(http_client=client)

    with pytest.raises(TelemetryProviderError) as exc_info:
        await provider.fetch_resource_state(namespace="sentinelscale", workload="demo-api")

    assert "authorization failure" in str(exc_info.value)


@pytest.mark.asyncio
async def test_kubernetes_timeout_raises_telemetry_provider_error():
    """Verify network timeout raises TelemetryProviderError."""
    async def timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("Kubernetes API read timeout")

    client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
    provider = KubernetesTelemetryProvider(http_client=client)

    with pytest.raises(TelemetryProviderError) as exc_info:
        await provider.fetch_resource_state(namespace="sentinelscale", workload="demo-api")

    assert "timed out" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resource_observer_service_with_kubernetes_provider():
    """Verify ResourceObserverService delegates seamlessly to KubernetesTelemetryProvider."""
    mock_deployment = {
        "spec": {"replicas": 2, "selector": {"matchLabels": {"app": "demo-api"}}}
    }
    mock_pods = {
        "items": [
            {"status": {"phase": "Running"}, "spec": {"containers": []}},
            {"status": {"phase": "Running"}, "spec": {"containers": []}},
        ]
    }
    mock_responses = {
        "deployments/demo-api": {"status_code": 200, "body": mock_deployment},
        "pods": {"status_code": 200, "body": mock_pods}
    }
    client = create_mock_k8s_transport(mock_responses)
    k8s_provider = KubernetesTelemetryProvider(http_client=client)
    observer = ResourceObserverService(provider=k8s_provider)

    state = await observer.get_current_resource_state(namespace="sentinelscale", workload="demo-api")
    assert state.running_pods == 2
    assert state.desired_pods == 2

