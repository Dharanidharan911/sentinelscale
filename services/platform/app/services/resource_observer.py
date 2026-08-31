from typing import Optional
from app.mock.generator import MockResourceDataGenerator
from app.models.resource import ResourceState


class ResourceObserverService:
    """
    Observes Kubernetes cluster metrics and pod states.
    Currently backed by deterministic mock generator for local development.
    """

    def __init__(self):
        self.mock_generator = MockResourceDataGenerator()

    async def get_current_resource_state(
        self,
        namespace: str = "sentinelscale",
        workload: str = "demo-api",
        trace_id: Optional[str] = None
    ) -> ResourceState:
        return self.mock_generator.generate_current_state(
            target_namespace=namespace,
            target_workload=workload,
            trace_id=trace_id
        )
