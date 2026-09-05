"""
SentinelScale — Demand Intelligence — Service Layer
Orchestrates: provider selection → observation retrieval → forecasting engine.

The service layer is the only place that knows which provider to use.
The forecasting engine knows nothing about providers.
The API layer knows nothing about provider selection.
"""
import time
from typing import List, Optional

from app.models.demand import DemandForecast, ForecastRequest, DemandObservation
from app.providers.base import DemandProvider
from app.providers.mock_provider import MockDemandProvider
from app.providers.prometheus_provider import PrometheusDemandProvider
from app.providers.static_provider import StaticObservationProvider
from app.engine.forecaster import produce_forecast
from app.config.settings import settings
from app.logging import logger


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
                              to inject a controlled provider. If None, uses
                              Prometheus when configured, otherwise the mock.
        """
        self._default_provider = default_provider

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
        started = time.perf_counter()
        provider = self._select_provider(request.observations, request.target_service)
        observations: List[DemandObservation] = provider.get_observations(
            window_seconds=request.historical_window_seconds or 3600
        )
        forecast = produce_forecast(
            observations=observations,
            forecast_horizon_seconds=request.forecast_horizon_seconds,
            trace_id=request.trace_id,
        )
        logger.info(
            "Demand forecast generated",
            extra={
                "provider": provider.name,
                "observation_count": len(observations),
                "forecast_horizon_seconds": request.forecast_horizon_seconds,
                "trace_id": forecast.trace_id,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return forecast

    def _select_provider(
        self,
        inline_observations: Optional[List[DemandObservation]],
        target_service: Optional[str],
    ) -> DemandProvider:
        if inline_observations:
            return StaticObservationProvider(inline_observations)
        if self._default_provider is not None:
            return self._default_provider
        if settings.PROMETHEUS_URL:
            return PrometheusDemandProvider(
                base_url=settings.PROMETHEUS_URL,
                query_template=settings.PROMETHEUS_QUERY,
                target_service=target_service or "demo-api",
                step_seconds=settings.PROMETHEUS_STEP_SECONDS,
                timeout_seconds=settings.PROMETHEUS_TIMEOUT_SECONDS,
            )
        return MockDemandProvider()
