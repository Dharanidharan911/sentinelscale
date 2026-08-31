from typing import Optional
from app.models.resource import ResourceState
from app.services.telemetry.base import ResourceTelemetryProvider
from app.services.telemetry.factory import get_telemetry_provider


class ResourceObserverService:
    """
    Resource Observer service aggregating infrastructure state and workload telemetry.
    Delegates metric querying to an injected ResourceTelemetryProvider.
    """

    def __init__(self, provider: Optional[ResourceTelemetryProvider] = None):
        self.provider = provider or get_telemetry_provider()

    async def get_current_resource_state(
        self,
        namespace: str = "sentinelscale",
        workload: str = "demo-api",
        trace_id: Optional[str] = None
    ) -> ResourceState:
        """
        Retrieve canonical ResourceState for a given target workload.
        """
        return await self.provider.fetch_resource_state(
            namespace=namespace,
            workload=workload,
            trace_id=trace_id
        )
