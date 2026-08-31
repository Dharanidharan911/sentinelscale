import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union
import httpx
import jsonschema
import pytest
from app.config.settings import settings
from app.models.resource import ResourceState
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.factory import get_telemetry_provider
from app.services.telemetry.prometheus_provider import PrometheusTelemetryProvider


def create_mock_prometheus_transport(query_responses: Union[Dict[str, dict], List[Tuple[str, dict]]]):
    """Creates a custom mock httpx.AsyncClient that responds to PromQL queries in evaluated order."""
    pairs = query_responses if isinstance(query_responses, list) else list(query_responses.items())

    async def handler(request: httpx.Request):
        query = str(request.url.params.get("query", ""))

        for pattern, response_data in pairs:
            if pattern == "*" or pattern in query:
                status = response_data.get("status_code", 200)
                body = response_data.get("body", {})
                if isinstance(body, str):
                    return httpx.Response(status_code=status, text=body)
                return httpx.Response(status_code=status, json=body)

        # Default empty vector
        return httpx.Response(
            status_code=200,
            json={"status": "success", "data": {"resultType": "vector", "result": []}}
        )

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


def test_prometheus_provider_implements_interface():
    """Verify PrometheusTelemetryProvider implements ResourceTelemetryProvider."""
    provider = PrometheusTelemetryProvider()
    assert isinstance(provider, ResourceTelemetryProvider)
    assert provider.provider_name == "prometheus"


def test_prometheus_url_configured_from_settings():
    """Verify provider respects settings.PROMETHEUS_URL."""
    custom_url = "http://custom-prom-host:9090"
    provider = PrometheusTelemetryProvider(base_url=custom_url)
    assert provider.base_url == custom_url


@pytest.mark.asyncio
async def test_successful_prometheus_telemetry_fetch_and_schema_conformance():
    """Verify parsing real Prometheus responses into canonical ResourceState conforming to JSON Schema."""
    mock_responses = [
        ('status=~"5.."', {
            "body": {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1725148800, "15.0"]}]
                }
            }
        }),
        ("http_requests_total", {
            "body": {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1725148800, "1500.5"]}]
                }
            }
        }),
        ("http_request_duration_seconds", {
            "body": {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1725148800, "38.2"]}]
                }
            }
        }),
        ("container_cpu_usage", {
            "body": {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1725148800, "2.4"]}]  # 2.4 cores used
                }
            }
        }),
        ("container_memory", {
            "body": {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1725148800, str(4 * 1024 * 1024 * 1024)]}]  # 4 GiB used
                }
            }
        }),
    ]
    client = create_mock_prometheus_transport(mock_responses)
    provider = PrometheusTelemetryProvider(http_client=client)

    state = await provider.fetch_resource_state(
        namespace="sentinelscale",
        workload="demo-api",
        trace_id="test-prom-trace-1"
    )

    assert isinstance(state, ResourceState)
    assert state.target_namespace == "sentinelscale"
    assert state.target_workload == "demo-api"
    assert state.trace_id == "test-prom-trace-1"
    assert state.request_rate == 1500.5
    assert state.p95_latency_ms == 38.2
    assert state.error_rate == round(15.0 / 1500.5, 4)
    # CPU: 2.4 cores / 8.0 limit = 0.30
    assert state.cpu_utilization == 0.30
    # Memory: 4 GiB / 8 GiB = 0.50
    assert state.memory_utilization == 0.50
    # Capacity: 4 pods * 350 RPS = 1400 RPS
    assert state.current_capacity_rps == 1400.0

    # JSON Schema Conformance
    schema_path = Path(__file__).resolve().parents[3] / "contracts" / "resources" / "resource_state.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(instance=state.model_dump(), schema=schema)


@pytest.mark.asyncio
async def test_raw_cpu_usage_is_not_interpreted_as_utilization_ratio():
    """Verify raw cores consumed (e.g. 2.0 cores) is normalized against limit (8.0 cores) -> 0.25, NOT 2.0."""
    mock_responses = {
        "container_cpu_usage": {
            "body": {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1725148800, "2.0"]}]
                }
            }
        }
    }
    client = create_mock_prometheus_transport(mock_responses)
    provider = PrometheusTelemetryProvider(http_client=client)

    cpu_ratio = await provider.query_cpu_utilization(
        workload="demo-api",
        cpu_limit_cores=8.0
    )
    assert cpu_ratio == 0.25
    assert 0.0 <= cpu_ratio <= 1.0


@pytest.mark.asyncio
async def test_missing_cpu_denominator_raises_explicit_error():
    """Verify invalid or missing CPU limit denominator raises TelemetryProviderError."""
    client = create_mock_prometheus_transport({})
    provider = PrometheusTelemetryProvider(http_client=client)

    with pytest.raises(TelemetryProviderError) as exc_info:
        await provider.query_cpu_utilization(
            workload="demo-api",
            cpu_limit_cores=0.0  # Invalid denominator
        )
    assert "invalid cpu_limit_cores" in str(exc_info.value)


@pytest.mark.asyncio
async def test_missing_memory_denominator_raises_explicit_error():
    """Verify invalid or missing memory limit denominator raises TelemetryProviderError."""
    client = create_mock_prometheus_transport({})
    provider = PrometheusTelemetryProvider(http_client=client)

    with pytest.raises(TelemetryProviderError) as exc_info:
        await provider.query_memory_utilization(
            workload="demo-api",
            memory_limit_bytes=0  # Invalid denominator
        )
    assert "invalid memory_limit_bytes" in str(exc_info.value)


@pytest.mark.asyncio
async def test_idle_service_zero_requests_returns_zero_error_rate():
    """Verify idle service (0 request rate) returns 0.0 error rate rather than division by zero."""
    mock_responses = {
        "http_requests_total": {
            "body": {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1725148800, "0.0"]}]
                }
            }
        }
    }
    client = create_mock_prometheus_transport(mock_responses)
    provider = PrometheusTelemetryProvider(http_client=client)

    error_rate = await provider.query_error_rate(workload="demo-api")
    assert error_rate == 0.0


@pytest.mark.asyncio
async def test_deterministic_capacity_and_waste_derivation():
    """Verify capacity and waste derivations are deterministic and follow documented formulas."""
    mock_responses = {
        "http_requests_total": {
            "body": {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1725148800, "700.0"]}]  # 700 RPS
                }
            }
        }
    }
    client = create_mock_prometheus_transport(mock_responses)
    provider = PrometheusTelemetryProvider(http_client=client)

    state = await provider.fetch_resource_state(namespace="sentinelscale", workload="demo-api")

    # 4 pods * 350 RPS capacity = 1400.0 RPS
    assert state.current_capacity_rps == 1400.0
    # Waste = (1400 - 700) / 1400 = 0.50 (50% overprovisioned capacity)
    assert state.estimated_resource_waste == 0.50
    assert state.estimated_required_capacity_rps == 700.0


@pytest.mark.asyncio
async def test_prometheus_http_500_raises_telemetry_provider_error():
    """Verify upstream HTTP 500 produces TelemetryProviderError."""
    mock_responses = {
        "*": {
            "status_code": 500,
            "body": "Internal Prometheus Error: storage corrupted"
        }
    }
    client = create_mock_prometheus_transport(mock_responses)
    provider = PrometheusTelemetryProvider(http_client=client)

    with pytest.raises(TelemetryProviderError) as exc_info:
        await provider.fetch_resource_state(namespace="sentinelscale", workload="demo-api")

    assert exc_info.value.provider_name == "prometheus"
    assert "Prometheus HTTP 500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_prometheus_malformed_json_raises_telemetry_provider_error():
    """Verify malformed non-JSON response produces TelemetryProviderError."""
    mock_responses = {
        "*": {
            "status_code": 200,
            "body": "<html><body>Bad Gateway</body></html>"
        }
    }
    client = create_mock_prometheus_transport(mock_responses)
    provider = PrometheusTelemetryProvider(http_client=client)

    with pytest.raises(TelemetryProviderError) as exc_info:
        await provider.fetch_resource_state(namespace="sentinelscale", workload="demo-api")

    assert "Malformed JSON" in str(exc_info.value)


@pytest.mark.asyncio
async def test_prometheus_timeout_raises_telemetry_provider_error():
    """Verify network timeouts produce TelemetryProviderError."""
    async def timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("Read timed out from prometheus")

    client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
    provider = PrometheusTelemetryProvider(http_client=client)

    with pytest.raises(TelemetryProviderError) as exc_info:
        await provider.fetch_resource_state(namespace="sentinelscale", workload="demo-api")

    assert "timed out" in str(exc_info.value)


def test_factory_returns_prometheus_provider():
    """Verify factory returns PrometheusTelemetryProvider when requested."""
    provider = get_telemetry_provider("prometheus")
    assert isinstance(provider, PrometheusTelemetryProvider)
    assert provider.provider_name == "prometheus"


@pytest.mark.asyncio
async def test_resource_observer_service_with_prometheus_provider():
    """Verify ResourceObserverService works seamlessly with PrometheusTelemetryProvider."""
    mock_responses = {
        "http_requests_total": {
            "body": {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1725148800, "1200.0"]}]
                }
            }
        }
    }
    client = create_mock_prometheus_transport(mock_responses)
    prom_provider = PrometheusTelemetryProvider(http_client=client)
    observer = ResourceObserverService(provider=prom_provider)

    state = await observer.get_current_resource_state(namespace="sentinelscale", workload="demo-api")
    assert state.request_rate == 1200.0
    assert state.target_workload == "demo-api"

