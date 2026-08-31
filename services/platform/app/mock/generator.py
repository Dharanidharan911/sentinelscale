import uuid
from datetime import datetime, timezone
from app.config.settings import settings
from app.models.resource import ResourceState


class MockResourceDataGenerator:
    """
    Deterministic Mock Generator for Kubernetes Resource State.
    Simulates real-time pod metrics and cluster telemetry.
    """

    @staticmethod
    def generate_current_state(
        target_namespace: str = "sentinelscale",
        target_workload: str = "demo-api",
        trace_id: str | None = None
    ) -> ResourceState:
        trace = trace_id or f"trace-{uuid.uuid4().hex[:16]}"
        return ResourceState(
            event_id=str(uuid.uuid4()),
            trace_id=trace,
            timestamp=datetime.now(timezone.utc).isoformat(),
            contract_version=settings.CONTRACT_VERSION,
            service_version=settings.SERVICE_VERSION,
            target_namespace=target_namespace,
            target_workload=target_workload,
            cpu_utilization=0.68,
            memory_utilization=0.52,
            cpu_requested_cores=4.0,
            cpu_limit_cores=8.0,
            memory_requested_bytes=4 * 1024 * 1024 * 1024,  # 4 GiB
            memory_limit_bytes=8 * 1024 * 1024 * 1024,     # 8 GiB
            running_pods=4,
            desired_pods=4,
            pending_pods=0,
            request_rate=2500.0,
            p95_latency_ms=42.5,
            error_rate=0.002,
            current_capacity_rps=1400.0,
            estimated_required_capacity_rps=1200.0,
            estimated_resource_waste=0.14
        )
