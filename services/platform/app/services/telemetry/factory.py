from typing import Optional
from app.config.settings import settings
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.mock_provider import MockTelemetryProvider
from app.services.telemetry.prometheus_provider import PrometheusTelemetryProvider
from app.services.telemetry.kubernetes_provider import KubernetesTelemetryProvider


def get_telemetry_provider(provider_type: Optional[str] = None) -> ResourceTelemetryProvider:
    """
    Factory creating the configured telemetry provider instance.
    Supports dependency injection and runtime configuration.
    """
    selected_type = (provider_type or settings.TELEMETRY_PROVIDER).lower().strip()

    if selected_type == "mock":
        return MockTelemetryProvider()
    elif selected_type == "prometheus":
        return PrometheusTelemetryProvider()
    elif selected_type == "kubernetes":
        return KubernetesTelemetryProvider()
    else:
        raise TelemetryProviderError(
            provider_name="factory",
            message=f"Unknown telemetry provider type: '{selected_type}'. Valid options: ['mock', 'prometheus', 'kubernetes']."
        )
