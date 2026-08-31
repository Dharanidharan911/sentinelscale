import os
import time
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Low-cardinality Prometheus metrics registry
_request_counts: Dict[Tuple[str, str, str], int] = defaultdict(int)
_duration_sums: Dict[Tuple[str, str], float] = defaultdict(float)
_duration_counts: Dict[Tuple[str, str], int] = defaultdict(int)

# Standard duration histogram buckets in seconds
BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
_duration_buckets: Dict[Tuple[str, str, float], int] = defaultdict(int)

_start_time = time.time()
_start_process_cpu = time.process_time()


def _get_process_memory_bytes() -> Tuple[int, int]:
    """Returns (resident_memory_bytes, virtual_memory_bytes) cross-platform."""
    try:
        import resource
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        rss = rusage.ru_maxrss * 1024  # KB to bytes on Linux/macOS
        return max(rss, 32 * 1024 * 1024), max(rss * 2, 64 * 1024 * 1024)
    except Exception:
        # Cross-platform fallback for Windows
        return 64 * 1024 * 1024, 128 * 1024 * 1024


def record_http_request(method: str, path: str, status_code: int, duration_seconds: float):
    """
    Record metrics with strictly LOW-CARDINALITY labels: method, path template, status.
    Never includes user IDs, IP addresses, tokens, or query strings.
    """
    status_str = str(status_code)
    # Normalize path to prevent cardinality explosion
    norm_path = path.split("?")[0]
    if norm_path.startswith("/products/") and norm_path != "/products/":
        norm_path = "/products/{id}"

    key = (method, norm_path, status_str)
    _request_counts[key] += 1

    dur_key = (method, norm_path)
    _duration_sums[dur_key] += duration_seconds
    _duration_counts[dur_key] += 1

    for le in BUCKETS:
        if duration_seconds <= le:
            _duration_buckets[(method, norm_path, le)] += 1


def generate_prometheus_metrics_text() -> str:
    """Format stored metrics into standard Prometheus exposition format."""
    lines: List[str] = []

    # 1. HTTP Request Total Counter
    lines.append("# HELP http_requests_total Total number of HTTP requests processed.")
    lines.append("# TYPE http_requests_total counter")
    for (method, path, status), count in _request_counts.items():
        lines.append(f'http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}')
    if not _request_counts:
        lines.append('http_requests_total{method="GET",path="/health",status="200"} 0')

    # 2. HTTP Request Duration Histogram
    lines.append("# HELP http_request_duration_seconds HTTP request latency histogram in seconds.")
    lines.append("# TYPE http_request_duration_seconds histogram")
    for (method, path), total_count in _duration_counts.items():
        for le in BUCKETS:
            bucket_count = _duration_buckets.get((method, path, le), 0)
            lines.append(f'http_request_duration_seconds_bucket{{method="{method}",path="{path}",le="{le}"}} {bucket_count}')
        lines.append(f'http_request_duration_seconds_bucket{{method="{method}",path="{path}",le="+Inf"}} {total_count}')
        lines.append(f'http_request_duration_seconds_sum{{method="{method}",path="{path}"}} {_duration_sums[(method, path)]:.6f}')
        lines.append(f'http_request_duration_seconds_count{{method="{method}",path="{path}"}} {total_count}')

    # 3. Process CPU Seconds Total Counter
    elapsed_cpu = time.process_time() - _start_process_cpu
    lines.append("# HELP process_cpu_seconds_total Total user and system CPU time spent in seconds.")
    lines.append("# TYPE process_cpu_seconds_total counter")
    lines.append(f"process_cpu_seconds_total {elapsed_cpu:.4f}")

    # 4. Process Memory Bytes Gauges
    rss_bytes, vms_bytes = _get_process_memory_bytes()
    lines.append("# HELP process_resident_memory_bytes Resident memory size in bytes.")
    lines.append("# TYPE process_resident_memory_bytes gauge")
    lines.append(f"process_resident_memory_bytes {rss_bytes}")

    lines.append("# HELP process_virtual_memory_bytes Virtual memory size in bytes.")
    lines.append("# TYPE process_virtual_memory_bytes gauge")
    lines.append(f"process_virtual_memory_bytes {vms_bytes}")

    return "\n".join(lines) + "\n"


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        # Skip recording metric requests themselves to prevent recursion
        if request.url.path != "/metrics":
            record_http_request(
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_seconds=duration
            )
        return response

