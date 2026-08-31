import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import httpx
from app.config.settings import settings
from app.logging import logger
from app.models.resource import ResourceState
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError


class PrometheusTelemetryProvider(ResourceTelemetryProvider):
    """
    Production-grade Prometheus Telemetry Provider for Platform Resource Observation.
    Queries Prometheus HTTP Instant Query API (/api/v1/query), extracts application and container
    metrics, normalizes utilization ratios, and populates canonical ResourceState.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        query_window: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = (base_url or settings.PROMETHEUS_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or settings.PROMETHEUS_TIMEOUT_SECONDS
        self.query_window = query_window or settings.PROMETHEUS_QUERY_WINDOW
        self._custom_client = http_client

    @property
    def provider_name(self) -> str:
        return "prometheus"

    async def _execute_instant_query(
        self,
        query: str,
        operation: str,
        trace_id: Optional[str] = None,
        allow_empty: bool = False,
        default_if_empty: float = 0.0,
    ) -> float:
        """
        Execute an instant PromQL query against Prometheus /api/v1/query.
        Raises TelemetryProviderError on connection failure, timeout, HTTP error, or malformed JSON.
        """
        start_time = time.perf_counter()
        query_url = f"{self.base_url}/api/v1/query"
        params = {"query": query}

        client = self._custom_client or httpx.AsyncClient(timeout=self.timeout_seconds)
        close_client = self._custom_client is None

        try:
            response = await client.get(query_url, params=params)
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

            if response.status_code != 200:
                logger.error(
                    f"Prometheus query '{operation}' failed with status {response.status_code}",
                    extra={
                        "service": "platform",
                        "provider": self.provider_name,
                        "trace_id": trace_id,
                        "operation": operation,
                        "status_code": response.status_code,
                        "latency_ms": latency_ms,
                    }
                )
                raise TelemetryProviderError(
                    provider_name=self.provider_name,
                    message=f"Prometheus HTTP {response.status_code} on {operation}: {response.text[:200]}"
                )

            try:
                data: Dict[str, Any] = response.json()
            except Exception as json_err:
                raise TelemetryProviderError(
                    provider_name=self.provider_name,
                    message=f"Malformed JSON response from Prometheus on {operation}",
                    original_error=json_err
                ) from json_err

            if data.get("status") != "success":
                err_msg = data.get("error", "Unknown Prometheus query error")
                raise TelemetryProviderError(
                    provider_name=self.provider_name,
                    message=f"Prometheus error on {operation}: {err_msg}"
                )

            result_vector = data.get("data", {}).get("result", [])
            if not result_vector:
                if allow_empty:
                    logger.info(
                        f"Empty result vector for {operation}; returning default {default_if_empty}",
                        extra={
                            "service": "platform",
                            "provider": self.provider_name,
                            "trace_id": trace_id,
                            "operation": operation,
                            "latency_ms": latency_ms,
                        }
                    )
                    return default_if_empty
                raise TelemetryProviderError(
                    provider_name=self.provider_name,
                    message=f"No telemetry metric data returned by Prometheus for {operation}"
                )

            # Extract scalar or first vector sample: result[0]["value"] -> [timestamp, "value_str"]
            sample_value = result_vector[0].get("value")
            if not sample_value or len(sample_value) < 2:
                raise TelemetryProviderError(
                    provider_name=self.provider_name,
                    message=f"Invalid metric value format in Prometheus response for {operation}"
                )

            val_float = float(sample_value[1])
            if math.isnan(val_float) or math.isinf(val_float):
                if allow_empty:
                    return default_if_empty
                raise TelemetryProviderError(
                    provider_name=self.provider_name,
                    message=f"Prometheus returned NaN/Inf for {operation}"
                )

            return val_float

        except httpx.TimeoutException as timeout_err:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                f"Prometheus query '{operation}' timed out after {self.timeout_seconds}s",
                extra={
                    "service": "platform",
                    "provider": self.provider_name,
                    "trace_id": trace_id,
                    "operation": operation,
                    "latency_ms": latency_ms,
                }
            )
            raise TelemetryProviderError(
                provider_name=self.provider_name,
                message=f"Prometheus query timed out on {operation} after {self.timeout_seconds}s",
                original_error=timeout_err
            ) from timeout_err
        except httpx.RequestError as req_err:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                f"Connection failure communicating with Prometheus on '{operation}'",
                extra={
                    "service": "platform",
                    "provider": self.provider_name,
                    "trace_id": trace_id,
                    "operation": operation,
                    "latency_ms": latency_ms,
                }
            )
            raise TelemetryProviderError(
                provider_name=self.provider_name,
                message=f"Failed to connect to Prometheus at {self.base_url}: {str(req_err)}",
                original_error=req_err
            ) from req_err
        finally:
            if close_client:
                await client.aclose()

    async def query_request_rate(self, workload: str, trace_id: Optional[str] = None) -> float:
        """
        Query incoming requests per second (RPS) over the query window.
        Distinguishes genuine 0 RPS (idle service) from query failures.
        """
        query = f'sum(rate(http_requests_total[{self.query_window}])) or sum(rate(http_requests_total{{job="sentinelscale-services"}}[{self.query_window}]))'
        val = await self._execute_instant_query(
            query=query,
            operation="query_request_rate",
            trace_id=trace_id,
            allow_empty=True,
            default_if_empty=0.0
        )
        return max(0.0, val)

    async def query_p95_latency(self, workload: str, trace_id: Optional[str] = None) -> float:
        """
        Query P95 response latency in milliseconds using histogram quantile.
        Falls back to average latency if histogram buckets are not populated.
        """
        query = (
            f'(histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[{self.query_window}])) by (le)) * 1000) '
            f'or ((sum(rate(http_request_duration_seconds_sum[{self.query_window}])) / sum(rate(http_request_duration_seconds_count[{self.query_window}]))) * 1000)'
        )
        val = await self._execute_instant_query(
            query=query,
            operation="query_p95_latency",
            trace_id=trace_id,
            allow_empty=True,
            default_if_empty=0.0
        )
        return max(0.0, val)

    async def query_error_rate(self, workload: str, trace_id: Optional[str] = None) -> float:
        """
        Query HTTP 5xx error rate ratio (0.0 - 1.0).
        Safely returns 0.0 when no requests occurred; fails explicitly if error telemetry is broken.
        """
        total_rate_query = f'sum(rate(http_requests_total[{self.query_window}]))'
        total_rate = await self._execute_instant_query(
            query=total_rate_query,
            operation="query_total_rate_for_errors",
            trace_id=trace_id,
            allow_empty=True,
            default_if_empty=0.0
        )

        if total_rate <= 0.0:
            return 0.0  # Idle service has 0.0 error rate

        err_query = f'sum(rate(http_requests_total{{status=~"5.."}}[{self.query_window}]))'
        err_rate = await self._execute_instant_query(
            query=err_query,
            operation="query_5xx_error_rate",
            trace_id=trace_id,
            allow_empty=True,
            default_if_empty=0.0
        )
        error_ratio = err_rate / total_rate
        return max(0.0, min(1.0, error_ratio))

    async def query_cpu_utilization(
        self,
        workload: str,
        cpu_limit_cores: float,
        trace_id: Optional[str] = None
    ) -> float:
        """
        Query CPU rate and normalize against cpu_limit_cores to produce utilization ratio (0.0 - 1.0).
        Explicitly rejects missing or invalid denominator.
        """
        if cpu_limit_cores <= 0.0:
            raise TelemetryProviderError(
                provider_name=self.provider_name,
                message=f"Cannot compute CPU utilization ratio: invalid cpu_limit_cores={cpu_limit_cores}"
            )

        query = (
            f'sum(rate(container_cpu_usage_seconds_total{{container=~".*{workload}.*"}}[{self.query_window}])) '
            f'or sum(rate(process_cpu_seconds_total[{self.query_window}]))'
        )
        raw_cpu_cores_used = await self._execute_instant_query(
            query=query,
            operation="query_cpu_utilization",
            trace_id=trace_id,
            allow_empty=True,
            default_if_empty=0.0
        )

        # Normalize raw cores into a 0.0 - 1.0 ratio
        cpu_ratio = raw_cpu_cores_used / cpu_limit_cores
        return max(0.0, cpu_ratio)

    async def query_memory_utilization(
        self,
        workload: str,
        memory_limit_bytes: int,
        trace_id: Optional[str] = None
    ) -> float:
        """
        Query resident memory bytes and normalize against memory_limit_bytes to produce ratio (0.0 - 1.0).
        Explicitly rejects missing or invalid denominator.
        """
        if memory_limit_bytes <= 0:
            raise TelemetryProviderError(
                provider_name=self.provider_name,
                message=f"Cannot compute Memory utilization ratio: invalid memory_limit_bytes={memory_limit_bytes}"
            )

        query = (
            f'sum(container_memory_working_set_bytes{{container=~".*{workload}.*"}}) '
            f'or sum(process_resident_memory_bytes)'
        )
        raw_memory_bytes = await self._execute_instant_query(
            query=query,
            operation="query_memory_utilization",
            trace_id=trace_id,
            allow_empty=True,
            default_if_empty=0.0
        )

        # Normalize raw bytes into a 0.0 - 1.0 ratio
        memory_ratio = raw_memory_bytes / float(memory_limit_bytes)
        return max(0.0, min(1.0, memory_ratio))

    async def fetch_resource_state(
        self,
        namespace: str = "sentinelscale",
        workload: str = "demo-api",
        trace_id: Optional[str] = None
    ) -> ResourceState:
        """
        Orchestrate real Prometheus queries, calculate derived capacity metrics,
        incorporate documented Phase 1B baseline assumptions, and generate ResourceState.
        """
        trace = trace_id or f"trace-{uuid.uuid4().hex[:16]}"

        # =========================================================================
        # 1. CONFIGURATION-BASED BASELINE ASSUMPTIONS (Phase 1B Documentation)
        # Note: In Phase 1B, pod replicas and resource spec limits are configuration-based
        # assumptions that will be provided dynamically by KubernetesTelemetryProvider in Phase 2.
        # =========================================================================
        cpu_requested_cores = settings.DEFAULT_BASELINE_CPU_REQUESTED_CORES
        cpu_limit_cores = settings.DEFAULT_BASELINE_CPU_LIMIT_CORES
        memory_requested_bytes = settings.DEFAULT_BASELINE_MEMORY_REQUESTED_BYTES
        memory_limit_bytes = settings.DEFAULT_BASELINE_MEMORY_LIMIT_BYTES
        running_pods = settings.DEFAULT_BASELINE_RUNNING_PODS
        desired_pods = settings.DEFAULT_BASELINE_RUNNING_PODS
        pending_pods = 0

        # =========================================================================
        # 2. REAL PROMETHEUS TELEMETRY QUERIES
        # =========================================================================
        request_rate = await self.query_request_rate(workload=workload, trace_id=trace)
        p95_latency_ms = await self.query_p95_latency(workload=workload, trace_id=trace)
        error_rate = await self.query_error_rate(workload=workload, trace_id=trace)
        cpu_utilization = await self.query_cpu_utilization(
            workload=workload,
            cpu_limit_cores=cpu_limit_cores,
            trace_id=trace
        )
        memory_utilization = await self.query_memory_utilization(
            workload=workload,
            memory_limit_bytes=memory_limit_bytes,
            trace_id=trace
        )

        # =========================================================================
        # 3. DERIVED METRICS & CAPACITY MODEL
        # =========================================================================
        # Capacity is derived from running_pods and configured capacity-per-pod assumption
        current_capacity_rps = running_pods * settings.DEFAULT_POD_RPS_CAPACITY
        estimated_required_capacity_rps = max(request_rate, 1.0)

        # Resource waste ratio: dimensionless overprovisioned capacity ratio [0.0, 1.0]
        if current_capacity_rps > 0.0:
            estimated_resource_waste = max(0.0, min(1.0, (current_capacity_rps - request_rate) / current_capacity_rps))
        else:
            estimated_resource_waste = 0.0

        return ResourceState(
            event_id=str(uuid.uuid4()),
            trace_id=trace,
            timestamp=datetime.now(timezone.utc).isoformat(),
            contract_version=settings.CONTRACT_VERSION,
            service_version=settings.SERVICE_VERSION,
            target_namespace=namespace,
            target_workload=workload,
            cpu_utilization=round(cpu_utilization, 4),
            memory_utilization=round(memory_utilization, 4),
            cpu_requested_cores=cpu_requested_cores,
            cpu_limit_cores=cpu_limit_cores,
            memory_requested_bytes=memory_requested_bytes,
            memory_limit_bytes=memory_limit_bytes,
            running_pods=running_pods,
            desired_pods=desired_pods,
            pending_pods=pending_pods,
            request_rate=round(request_rate, 2),
            p95_latency_ms=round(p95_latency_ms, 2),
            error_rate=round(error_rate, 4),
            current_capacity_rps=round(current_capacity_rps, 2),
            estimated_required_capacity_rps=round(estimated_required_capacity_rps, 2),
            estimated_resource_waste=round(estimated_resource_waste, 4),
        )

