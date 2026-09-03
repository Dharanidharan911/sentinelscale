"""
SentinelScale — Demand Intelligence — Service Layer
Orchestrates: provider selection → observation retrieval → forecasting engine.

The service layer is the only place that knows which provider to use.
The forecasting engine knows nothing about providers.
The API layer knows nothing about provider selection.
"""
from typing import List, Optional

from app.models.demand import DemandForecast, ForecastRequest, DemandObservation
from app.providers.base import DemandProvider
from app.providers.mock_provider import MockDemandProvider
from app.providers.static_provider import StaticObservationProvider
from app.engine.forecaster import produce_forecast


class DemandForecastingService:
    """
    Demand Intelligence service layer.

    Selects the appropriate provider based on request content:
    - If the request includes explicit observations → StaticObservationProvider
    - Otherwise → MockDemandProvider (or real telemetry provider in future)

    The Decision Engine (Member 3) should call this service through the
    POST /api/v1/demand/forecast HTTP endpoint, not by importing this class.
    """

    def __init__(self, default_provider: Optional[DemandProvider] = None):
        """
        Args:
            default_provider: Override the default provider. Used in tests
                              to inject a controlled mock. If None, a fresh
                              MockDemandProvider is used.
        """
        self._default_provider = default_provider or MockDemandProvider()

    async def forecast_demand(self, request: ForecastRequest) -> DemandForecast:
        """
        Produce a DemandForecast for the given request.

        Provider selection:
            1. If request.observations is provided and non-empty →
               use StaticObservationProvider (caller-supplied data)
            2. Otherwise → use the default provider (mock / telemetry)

        Errors propagate explicitly:
            - InsufficientDataError → HTTP 422
            - InvalidObservationError → HTTP 422
            - ProviderUnavailableError → HTTP 503
        """
        provider = self._select_provider(request.observations)
        observations: List[DemandObservation] = provider.get_observations(
            window_seconds=request.historical_window_seconds or 3600
        )
        return produce_forecast(
            observations=observations,
            forecast_horizon_seconds=request.forecast_horizon_seconds,
            trace_id=request.trace_id,
        )

    def _select_provider(
        self,
        inline_observations: Optional[List[DemandObservation]],
    ) -> DemandProvider:
        if inline_observations:
            return StaticObservationProvider(inline_observations)
        return self._default_provider
