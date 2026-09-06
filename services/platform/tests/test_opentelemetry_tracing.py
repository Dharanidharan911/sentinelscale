"""
Tests for SentinelScale OpenTelemetry Tracing Foundation (Stage M3-9)
Validates:
- TracerProvider lifecycle (init, shutdown, disable)
- W3C TraceContext propagation (inject, extract)
- Boundary span creation, attribute enrichment, and exception recording
- Trace-to-log correlation (JsonFormatter enrichment and middleware headers)
- HTTP client context injection
- DecisionEngine span instrumentation
- OpenTelemetry Collector config and manifests
"""

import json
import logging
from unittest.mock import AsyncMock, MagicMock
import pytest
from pathlib import Path
import httpx

from app.config.settings import settings
from app.logging import JsonFormatter
from app.models.context import DecisionContext, PolicyOverrides
from app.models.traffic_contract import TrafficClassification
from app.services.decision_engine import DecisionEngine
from tests.fixtures_decision import make_decision_context, make_traffic_assessment, make_demand_forecast, make_resource_state
from app.telemetry.tracing import (
    init_tracing,
    shutdown_tracing,
    is_tracing_enabled,
    get_tracer,
    create_span,
    get_current_trace_id,
    get_current_span_id,
    inject_trace_context,
    extract_trace_context,
    OTEL_AVAILABLE,
    InMemorySpanExporter,
)


@pytest.fixture(autouse=True)
def clean_tracing_state():
    """Ensure clean tracing state before and after each test."""
    shutdown_tracing()
    yield
    shutdown_tracing()


def test_tracing_init_disabled():
    """When disabled in config or args, tracing is disabled and returns None."""
    provider = init_tracing(enabled=False)
    assert provider is None
    assert is_tracing_enabled() is False
    assert get_current_trace_id() is None
    assert get_current_span_id() is None


def test_tracing_init_and_span_lifecycle():
    """When initialized with memory processor, spans record attributes and active IDs."""
    if not OTEL_AVAILABLE:
        pytest.skip("OpenTelemetry SDK not installed")

    exporter = InMemorySpanExporter()
    provider = init_tracing(
        service_name="test-sentinelscale",
        enabled=True,
        sampling_ratio=1.0,
        use_simple_processor=True,
        exporter=exporter,
    )
    assert provider is not None
    assert is_tracing_enabled() is True

    # Outside span
    assert get_current_trace_id() is None

    # Inside span
    with create_span("test_operation", attributes={"custom.key": "custom_val", "number.key": 42}) as span:
        assert span is not None
        trace_id = get_current_trace_id()
        span_id = get_current_span_id()
        assert trace_id is not None
        assert len(trace_id) == 32
        assert span_id is not None
        assert len(span_id) == 16

    # Outside span again
    assert get_current_trace_id() is None

    # Check exported span
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test_operation"
    assert spans[0].attributes["custom.key"] == "custom_val"
    assert spans[0].attributes["number.key"] == 42


def test_tracing_exception_recording():
    """Exceptions raised within create_span are recorded on span and re-raised."""
    if not OTEL_AVAILABLE:
        pytest.skip("OpenTelemetry SDK not installed")

    exporter = InMemorySpanExporter()
    init_tracing(enabled=True, sampling_ratio=1.0, use_simple_processor=True, exporter=exporter)

    with pytest.raises(ValueError, match="Synthetic test error"):
        with create_span("failing_operation") as span:
            assert span is not None
            raise ValueError("Synthetic test error")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "failing_operation"
    assert spans[0].status.status_code.name == "ERROR"


def test_w3c_trace_context_propagation():
    """W3C traceparent header is correctly injected and extracted."""
    if not OTEL_AVAILABLE:
        pytest.skip("OpenTelemetry SDK not installed")

    exporter = InMemorySpanExporter()
    init_tracing(enabled=True, sampling_ratio=1.0, use_simple_processor=True, exporter=exporter)

    headers = {}
    with create_span("parent_span"):
        trace_id = get_current_trace_id()
        inject_trace_context(headers)

        assert "traceparent" in headers
        # W3C traceparent format: 00-{32hex_trace_id}-{16hex_span_id}-{2hex_flags}
        parts = headers["traceparent"].split("-")
        assert len(parts) == 4
        assert parts[0] == "00"
        assert parts[1] == trace_id

    # Extraction test
    extracted_ctx = extract_trace_context(headers)
    assert extracted_ctx is not None


def test_log_correlation_json_formatter():
    """JsonFormatter includes otel_trace_id and otel_span_id when a span is active."""
    if not OTEL_AVAILABLE:
        pytest.skip("OpenTelemetry SDK not installed")

    exporter = InMemorySpanExporter()
    init_tracing(enabled=True, sampling_ratio=1.0, use_simple_processor=True, exporter=exporter)
    formatter = JsonFormatter()

    # Log record without active span
    record_no_span = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Message without span",
        args=(),
        exc_info=None,
    )
    formatted_no_span = json.loads(formatter.format(record_no_span))
    assert "otel_trace_id" not in formatted_no_span or formatted_no_span.get("otel_trace_id") is None

    # Log record within active span
    with create_span("logged_operation"):
        trace_id = get_current_trace_id()
        span_id = get_current_span_id()

        record_with_span = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=2,
            msg="Message with span",
            args=(),
            exc_info=None,
        )
        formatted_with_span = json.loads(formatter.format(record_with_span))
        assert formatted_with_span.get("otel_trace_id") == trace_id
        assert formatted_with_span.get("otel_span_id") == span_id


@pytest.mark.asyncio
async def test_traffic_client_w3c_header_injection():
    """TrafficIntelligenceClient injects W3C traceparent headers into outbound HTTP requests."""
    from app.clients.traffic_client import TrafficIntelligenceClient

    if not OTEL_AVAILABLE:
        pytest.skip("OpenTelemetry SDK not installed")

    exporter = InMemorySpanExporter()
    init_tracing(enabled=True, sampling_ratio=1.0, use_simple_processor=True, exporter=exporter)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = make_traffic_assessment(trace_id="trace-test-123").model_dump(mode="json")
    mock_resp.raise_for_status = MagicMock()

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.post = AsyncMock(return_value=mock_resp)

    client = TrafficIntelligenceClient(base_url="http://mock-traffic:8001", http_client=mock_http)

    with create_span("client_caller_span"):
        expected_trace_id = get_current_trace_id()
        assessment = await client.fetch_assessment(window_seconds=60, trace_id="trace-test-123")
        assert assessment.trace_id == "trace-test-123"

        mock_http.post.assert_called_once()
        call_kwargs = mock_http.post.call_args.kwargs
        assert "headers" in call_kwargs
        headers = call_kwargs["headers"]
        assert "traceparent" in headers
        assert expected_trace_id in headers["traceparent"]


@pytest.mark.asyncio
async def test_demand_client_w3c_header_injection():
    """DemandIntelligenceClient injects W3C traceparent headers into outbound HTTP requests."""
    from app.clients.demand_client import DemandIntelligenceClient

    if not OTEL_AVAILABLE:
        pytest.skip("OpenTelemetry SDK not installed")

    exporter = InMemorySpanExporter()
    init_tracing(enabled=True, sampling_ratio=1.0, use_simple_processor=True, exporter=exporter)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = make_demand_forecast(trace_id="trace-test-123").model_dump(mode="json")
    mock_resp.raise_for_status = MagicMock()

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.post = AsyncMock(return_value=mock_resp)

    client = DemandIntelligenceClient(base_url="http://mock-demand:8002", http_client=mock_http)

    with create_span("client_caller_span"):
        expected_trace_id = get_current_trace_id()
        forecast = await client.fetch_forecast(forecast_horizon_seconds=300, trace_id="trace-test-123")
        assert forecast.trace_id == "trace-test-123"

        mock_http.post.assert_called_once()
        call_kwargs = mock_http.post.call_args.kwargs
        assert "headers" in call_kwargs
        headers = call_kwargs["headers"]
        assert "traceparent" in headers
        assert expected_trace_id in headers["traceparent"]


@pytest.mark.asyncio
async def test_decision_engine_span_instrumentation():
    """DecisionEngine emits spans with evaluation attributes."""
    if not OTEL_AVAILABLE:
        pytest.skip("OpenTelemetry SDK not installed")

    exporter = InMemorySpanExporter()
    init_tracing(enabled=True, sampling_ratio=1.0, use_simple_processor=True, exporter=exporter)

    engine = DecisionEngine()
    context = make_decision_context(trace_id="trace-abc")

    with create_span("outer_decision_span"):
        decision = await engine.evaluate_decision(context)
        assert decision.trace_id == "trace-abc"

    spans = exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert "decision_engine.evaluate_decision" in span_names
    eval_span = next(s for s in spans if s.name == "decision_engine.evaluate_decision")
    assert eval_span.attributes["decision.action"] == decision.action.value
    assert eval_span.attributes["workload"] == "demo-api"


def test_otel_collector_compose_and_k8s_manifests():
    """Validates OpenTelemetry Collector configuration file and k8s manifests."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent

    # 1. Check docker-compose otel-collector configuration
    config_path = repo_root / "telemetry" / "otel" / "otel-collector-config.yaml"
    assert config_path.exists(), "telemetry/otel/otel-collector-config.yaml must exist"
    config_content = config_path.read_text(encoding="utf-8")

    assert "receivers:" in config_content
    assert "otlp:" in config_content
    assert "endpoint: 0.0.0.0:4317" in config_content
    assert "endpoint: 0.0.0.0:4318" in config_content
    assert "traces:" in config_content

    # 2. Check Kubernetes manifests
    cm_path = repo_root / "infrastructure" / "kubernetes" / "otel-collector" / "configmap.yaml"
    dep_path = repo_root / "infrastructure" / "kubernetes" / "otel-collector" / "deployment.yaml"
    svc_path = repo_root / "infrastructure" / "kubernetes" / "otel-collector" / "service.yaml"

    assert cm_path.exists()
    assert dep_path.exists()
    assert svc_path.exists()

    cm_content = cm_path.read_text(encoding="utf-8")
    assert "kind: ConfigMap" in cm_content
    assert "name: otel-collector-config" in cm_content

    dep_content = dep_path.read_text(encoding="utf-8")
    assert "kind: Deployment" in dep_content
    assert "name: otel-collector" in dep_content
    assert "otel/opentelemetry-collector-contrib:0.96.0" in dep_content

    svc_content = svc_path.read_text(encoding="utf-8")
    assert "kind: Service" in svc_content
    assert "name: otel-collector" in svc_content
    assert "port: 4317" in svc_content
    assert "port: 4318" in svc_content
