from abc import ABC, abstractmethod
from typing import Optional
from app.models.resource import ResourceState


class TelemetryProviderError(Exception):
    """
    Raised when a telemetry provider fails to fetch, parse, or reach upstream telemetry.
    Explicit failure representation preventing silent emission of fake production telemetry.
    """
    def __init__(self, provider_name: str, message: str, original_error: Optional[Exception] = None):
        self.provider_name = provider_name
        self.message = message
        self.original_error = original_error
        super().__init__(f"[{provider_name}] {message}")


class ResourceTelemetryProvider(ABC):
    """
    Abstract Telemetry Provider Interface for Platform Resource Observation.
    Encapsulates infrastructure-specific metric collection (Mock, Prometheus, Kubernetes).
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique identifier name of the provider."""
        pass

    @abstractmethod
    async def fetch_resource_state(
        self,
        namespace: str,
        workload: str,
        trace_id: Optional[str] = None
    ) -> ResourceState:
        """
        Fetch canonical ResourceState for a given target workload.
        Must raise TelemetryProviderError on upstream connection or query failure.
        """
        pass

