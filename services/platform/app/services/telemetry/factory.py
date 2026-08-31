from typing import Optional
from app.config.settings import settings
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.mock_provider import MockTelemetryProvider


def get_telemetry_provider(provider_type: Optional[str] = None) -> ResourceTelemetryProvider:
    """
    Factory creating the configured telemetry provider instance.
    Supports dependency injection and runtime configuration.
    """
    selected_type = (provider_type or settings.TELEMETRY_PROVIDER).lower().strip()

    if selected_type == "mock":
        return MockTelemetryProvider()
    elif selected_type in ("prometheus", "kubernetes"):
        raise NotImplementedError(
            f"Provider '{selected_type}' is scheduled for Phase 1 expansion and not yet active. "
            "Use TELEMETRY_PROVIDER=mock."
        )
    else:
        raise TelemetryProviderError(
            provider_name="factory",
            message=f"Unknown telemetry provider type: '{selected_type}'. Valid options: ['mock', 'prometheus', 'kubernetes']."
        )

