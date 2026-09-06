"""
SentinelScale Stage M3-9: OpenTelemetry Distributed Tracing Foundation

Provides production-grade OpenTelemetry initialization, W3C TraceContext propagation,
service boundary span management, and trace-to-log correlation helpers.

CRITICAL SAFETY INVARIANTS:
- Observability only: Tracing failures never cause business requests to fail.
- Zero Kubernetes scaling mutations.
- Frozen v1.0.0 contracts remain unchanged.
"""

from contextlib import contextmanager
import logging
from typing import Any, Dict, Iterator, Optional

_logger = logging.getLogger("platform.telemetry.tracing")

# Try importing OpenTelemetry packages with graceful fallback
try:
    from opentelemetry import trace, propagate
    from opentelemetry.trace import Tracer, Span, StatusCode, Status, get_tracer_provider, set_tracer_provider
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    try:
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    except ImportError:
        InMemorySpanExporter = None
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased, ALWAYS_ON, ALWAYS_OFF
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    trace = None
    propagate = None
    Tracer = Any
    Span = Any
    StatusCode = None
    InMemorySpanExporter = None

_tracer_provider: Optional[Any] = None
_tracing_initialized: bool = False
_tracing_enabled: bool = False


def is_tracing_enabled() -> bool:
    """Returns whether OpenTelemetry tracing is currently active."""
    return _tracing_enabled and OTEL_AVAILABLE


def init_tracing(
    service_name: Optional[str] = None,
    otlp_endpoint: Optional[str] = None,
    enabled: Optional[bool] = None,
    sampling_ratio: Optional[float] = None,
    use_simple_processor: bool = False,
    exporter: Optional[Any] = None,
) -> Optional[Any]:
    """
    Initializes the OpenTelemetry TracerProvider with OTLP HTTP span exporter.
    Gracefully handles missing packages or unavailable endpoints.
    """
    global _tracer_provider, _tracing_initialized, _tracing_enabled

    from app.config.settings import settings

    service_name = service_name or settings.OTEL_SERVICE_NAME
    otlp_endpoint = otlp_endpoint or settings.OTEL_EXPORTER_OTLP_ENDPOINT
    enabled = enabled if enabled is not None else settings.OTEL_TRACES_ENABLED
    sampling_ratio = sampling_ratio if sampling_ratio is not None else settings.OTEL_SAMPLING_RATIO

    if not OTEL_AVAILABLE:
        _logger.warning("OpenTelemetry packages not available; tracing disabled.")
        _tracing_enabled = False
        _tracing_initialized = True
        return None

    if not enabled:
        _tracing_enabled = False
        _tracing_initialized = True
        _logger.info("OpenTelemetry tracing is disabled by configuration.")
        return None

    try:
        # Create Resource metadata
        resource = Resource.create({
            "service.name": service_name,
            "service.version": settings.SERVICE_VERSION,
            "deployment.environment": settings.ENVIRONMENT,
        })

        # Sampler configuration
        if sampling_ratio >= 1.0:
            sampler = ALWAYS_ON
        elif sampling_ratio <= 0.0:
            sampler = ALWAYS_OFF
        else:
            sampler = TraceIdRatioBased(sampling_ratio)

        provider = TracerProvider(resource=resource, sampler=sampler)

        # Configure span exporter if not provided
        if exporter is None:
            endpoint = (otlp_endpoint or "http://localhost:4318").rstrip("/")
            if not endpoint.endswith("/v1/traces"):
                traces_url = f"{endpoint}/v1/traces"
            else:
                traces_url = endpoint
            exporter = OTLPSpanExporter(endpoint=traces_url, timeout=2.0)
            exporter_desc = traces_url
        else:
            exporter_desc = type(exporter).__name__

        # BatchSpanProcessor is standard for production; SimpleSpanProcessor useful for testing
        if use_simple_processor:
            processor = SimpleSpanProcessor(exporter)
        else:
            processor = BatchSpanProcessor(exporter, max_queue_size=2048, schedule_delay_millis=5000)

        provider.add_span_processor(processor)

        # Set as global tracer provider
        try:
            set_tracer_provider(provider)
        except Exception:
            pass
        _tracer_provider = provider
        _tracing_enabled = True
        _tracing_initialized = True

        # Set W3C TraceContext propagator globally
        propagate.set_global_textmap(TraceContextTextMapPropagator())

        _logger.info(f"OpenTelemetry tracing initialized: service={service_name}, exporter={exporter_desc}")
        return provider

    except Exception as err:
        _logger.warning(f"Failed to initialize OpenTelemetry tracing: {err}. Falling back to no-op.", exc_info=True)
        _tracing_enabled = False
        _tracing_initialized = True
        return None


def get_tracer(name: str = "platform") -> Any:
    """Returns a tracer instance from the active TracerProvider or no-op tracer."""
    if not OTEL_AVAILABLE or not _tracing_enabled:
        if OTEL_AVAILABLE:
            return trace.get_tracer(name)
        return None
    if _tracer_provider is not None:
        return _tracer_provider.get_tracer(name)
    return trace.get_tracer(name)


def get_current_trace_id() -> Optional[str]:
    """
    Returns the active 32-character hexadecimal OpenTelemetry trace ID,
    or None if no span is active.
    """
    if not OTEL_AVAILABLE or not _tracing_enabled:
        return None
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.get_span_context().is_valid:
            return format(current_span.get_span_context().trace_id, "032x")
    except Exception:
        pass
    return None


def get_current_span_id() -> Optional[str]:
    """
    Returns the active 16-character hexadecimal OpenTelemetry span ID,
    or None if no span is active.
    """
    if not OTEL_AVAILABLE or not _tracing_enabled:
        return None
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.get_span_context().is_valid:
            return format(current_span.get_span_context().span_id, "016x")
    except Exception:
        pass
    return None


def inject_trace_context(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Injects W3C TraceContext headers (e.g. traceparent) into the provided HTTP headers dict.
    """
    if not OTEL_AVAILABLE or not _tracing_enabled:
        return headers
    try:
        propagate.inject(headers)
    except Exception as err:
        _logger.debug(f"Failed to inject trace context: {err}")
    return headers


def extract_trace_context(headers: Dict[str, str]) -> Any:
    """
    Extracts W3C TraceContext from incoming HTTP headers dict into an OpenTelemetry Context.
    """
    if not OTEL_AVAILABLE or not _tracing_enabled:
        return None
    try:
        return propagate.extract(headers)
    except Exception as err:
        _logger.debug(f"Failed to extract trace context: {err}")
        return None


@contextmanager
def create_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    tracer_name: str = "platform"
) -> Iterator[Optional[Any]]:
    """
    Context manager for creating observational spans across business boundaries.
    Automatically captures exceptions, updates span status, and sets attributes.
    """
    if not OTEL_AVAILABLE or not _tracing_enabled:
        yield None
        return

    tracer = get_tracer(tracer_name)
    if not tracer:
        yield None
        return

    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                if v is not None:
                    span.set_attribute(k, str(v) if not isinstance(v, (int, float, bool, str)) else v)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def shutdown_tracing() -> None:
    """Flushes and shuts down the active TracerProvider."""
    global _tracer_provider, _tracing_initialized, _tracing_enabled
    if _tracer_provider and hasattr(_tracer_provider, "shutdown"):
        try:
            _tracer_provider.shutdown()
        except Exception as err:
            _logger.debug(f"Error during tracing shutdown: {err}")
    _tracer_provider = None
    _tracing_initialized = False
    _tracing_enabled = False
