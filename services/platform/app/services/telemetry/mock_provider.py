from typing import Optional
from app.mock.generator import MockResourceDataGenerator
from app.models.resource import ResourceState
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError


class MockTelemetryProvider(ResourceTelemetryProvider):
    """
    Deterministic Mock Telemetry Provider for local development, tests, and dry-run environments.
    """

    def __init__(self, should_fail: bool = False, failure_message: str = "Simulated mock provider failure"):
        self._should_fail = should_fail
        self._failure_message = failure_message
        self._generator = MockResourceDataGenerator()

    @property
    def provider_name(self) -> str:
        return "mock"

    async def fetch_resource_state(
        self,
        namespace: str,
        workload: str,
        trace_id: Optional[str] = None
    ) -> ResourceState:
        if self._should_fail:
            raise TelemetryProviderError(
                provider_name=self.provider_name,
                message=self._failure_message
            )
        return self._generator.generate_current_state(
            target_namespace=namespace,
            target_workload=workload,
            trace_id=trace_id
        )

