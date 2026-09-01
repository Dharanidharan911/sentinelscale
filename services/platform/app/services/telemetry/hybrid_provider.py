import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config.settings import settings
from app.logging import logger
from app.models.resource import ResourceState
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.kubernetes_provider import KubernetesTelemetryProvider
from app.services.telemetry.prometheus_provider import PrometheusTelemetryProvider


class HybridTelemetryProvider(ResourceTelemetryProvider):
    """
    Hybrid Telemetry Provider (Phase 2B): composes the existing Kubernetes and
    Prometheus providers into a single canonical ResourceState.

    Orchestration flow:
      1. Kubernetes provider observes real infrastructure state (pod counts,
         aggregated container requests/limits).
      2. The real Kubernetes limits are passed as normalization denominators to
         the Prometheus provider's utilization queries.
      3. Independent Prometheus queries run concurrently (asyncio.gather).
      4. Results are composed into ONE coherent ResourceState with fresh,
         consistent metadata (single event_id/timestamp, propagated trace_id).

    The hybrid provider duplicates neither Prometheus query logic nor
    Kubernetes REST/quantity-parsing/auth logic: it only orchestrates the
    existing providers behind the ResourceTelemetryProvider abstraction.

    Failure policy: if either upstream provider fails, a controlled
    TelemetryProviderError is raised (chained to the original error). No mock
    fallback and no fabricated telemetry is ever emitted.
    """

    def __init__(
        self,
        kubernetes_provider: Optional[KubernetesTelemetryProvider] = None,
        prometheus_provider: Optional[PrometheusTelemetryProvider] = None,
    ):
        self.kubernetes_provider = kubernetes_provider or KubernetesTelemetryProvider()
        self.prometheus_provider = prometheus_provider or PrometheusTelemetryProvider()

    @property
    def provider_name(self) -> str:
        return "hybrid"

    async def fetch_resource_state(
        self,
        namespace: str = "sentinelscale",
        workload: str = "demo-api",
        trace_id: Optional[str] = None
    ) -> ResourceState:
        """
        Compose one canonical ResourceState from Kubernetes infrastructure
        telemetry and Prometheus application/runtime telemetry.
        Raises TelemetryProviderError when either upstream provider fails.
        """
        trace = trace_id or f"trace-{uuid.uuid4().hex[:16]}"

        # =========================================================================
        # 1. KUBERNETES INFRASTRUCTURE TELEMETRY (FIRST — provides real limits)
        # =========================================================================
        try:
            k8s_state = await self.kubernetes_provider.fetch_resource_state(
                namespace=namespace,
                workload=workload,
                trace_id=trace
            )
        except TelemetryProviderError as k8s_err:
            logger.error(
                "Hybrid telemetry aborted: Kubernetes provider failure",
                extra={
                    "service": "platform",
                    "provider": self.provider_name,
                    "trace_id": trace,
                    "upstream_provider": k8s_err.provider_name,
                }
            )
            raise TelemetryProviderError(
                provider_name=self.provider_name,
                message=f"Kubernetes telemetry failed during hybrid observation: {k8s_err.message}",
                original_error=k8s_err
            ) from k8s_err

        # =========================================================================
        # 2. PROMETHEUS RUNTIME TELEMETRY (CONCURRENT, normalized with real
        #    Kubernetes limits instead of configuration baseline assumptions)
        # =========================================================================
        try:
            request_rate, p95_latency_ms, error_rate, cpu_utilization, memory_utilization = await asyncio.gather(
                self.prometheus_provider.query_request_rate(
                    workload=workload, trace_id=trace
                ),
                self.prometheus_provider.query_p95_latency(
                    workload=workload, trace_id=trace
                ),
                self.prometheus_provider.query_error_rate(
                    workload=workload, trace_id=trace
                ),
                self.prometheus_provider.query_cpu_utilization(
                    workload=workload,
                    cpu_limit_cores=k8s_state.cpu_limit_cores,
                    trace_id=trace
                ),
                self.prometheus_provider.query_memory_utilization(
                    workload=workload,
                    memory_limit_bytes=k8s_state.memory_limit_bytes,
                    trace_id=trace
                ),
            )
        except TelemetryProviderError as prom_err:
            logger.error(
                "Hybrid telemetry aborted: Prometheus provider failure",
                extra={
                    "service": "platform",
                    "provider": self.provider_name,
                    "trace_id": trace,
                    "upstream_provider": prom_err.provider_name,
                }
            )
            raise TelemetryProviderError(
                provider_name=self.provider_name,
                message=f"Prometheus telemetry failed during hybrid observation: {prom_err.message}",
                original_error=prom_err
            ) from prom_err

        # =========================================================================
        # 3. DERIVED METRICS & CAPACITY MODEL (existing formulas preserved)
        # =========================================================================
        current_capacity_rps = k8s_state.running_pods * settings.DEFAULT_POD_RPS_CAPACITY
        estimated_required_capacity_rps = max(request_rate, 1.0)

        # Resource waste ratio: dimensionless overprovisioned capacity ratio [0.0, 1.0]
        if current_capacity_rps > 0.0:
            estimated_resource_waste = max(0.0, min(1.0, (current_capacity_rps - request_rate) / current_capacity_rps))
        else:
            estimated_resource_waste = 0.0

        # =========================================================================
        # 4. COMPOSE ONE COHERENT ResourceState (fresh, consistent metadata)
        # =========================================================================
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
            cpu_requested_cores=k8s_state.cpu_requested_cores,
            cpu_limit_cores=k8s_state.cpu_limit_cores,
            memory_requested_bytes=k8s_state.memory_requested_bytes,
            memory_limit_bytes=k8s_state.memory_limit_bytes,
            running_pods=k8s_state.running_pods,
            desired_pods=k8s_state.desired_pods,
            pending_pods=k8s_state.pending_pods,
            request_rate=round(request_rate, 2),
            p95_latency_ms=round(p95_latency_ms, 2),
            error_rate=round(error_rate, 4),
            current_capacity_rps=round(current_capacity_rps, 2),
            estimated_required_capacity_rps=round(estimated_required_capacity_rps, 2),
            estimated_resource_waste=round(estimated_resource_waste, 4),
        )