"""
SentinelScale — Demand Intelligence — Service Layer (M2-7)
Orchestrates: provider selection → observation retrieval → forecasting engine selection.

The service layer is the single place that knows:
1. Which observation provider to use (Static, Prometheus, Mock).
2. Which forecasting engine to invoke (Baseline RWMA or Feature-Engineered ML Ridge).

The API layer and downstream consumers remain unaware of provider/model internals.
The output contract is strictly DemandForecast v1.0.0.
"""
import time
from typing import List, Optional

from app.models.demand import DemandForecast, ForecastRequest, DemandObservation
from app.providers.base import DemandProvider
from app.providers.mock_provider import MockDemandProvider
from app.providers.prometheus_provider import PrometheusDemandProvider
from app.providers.static_provider import StaticObservationProvider
from app.engine.forecaster import produce_forecast
from app.engine.ml_forecaster import MLDemandForecaster
from app.engine.explainability import ForecastExplainer, ForecastExplanation
from app.config.settings import settings
from app.logging import logger


class DemandForecastingService:
    """
    Demand Intelligence service layer.

    Selects the appropriate observation provider:
    - If request includes explicit observations → StaticObservationProvider
    - Otherwise → Injected provider, PrometheusDemandProvider, or MockDemandProvider

    Selects the appropriate forecasting engine:
    - If configured for ML ("ml" or "demand-ml-v1") → MLDemandForecaster (with baseline fallback)
    - Otherwise → Baseline produce_forecast (demand-v1)

    The Decision Engine (Member 3) consumes this service through HTTP
    POST /api/v1/demand/forecast, receiving DemandForecast v1.0.0.
    """

    def __init__(
        self,
        default_provider: Optional[DemandProvider] = None,
        model_type: Optional[str] = None,
    ):
        """
        Args:
            default_provider: Override the default provider. Used in tests
                              to inject a controlled provider. If None, uses
                              Prometheus when configured, otherwise the mock.
            model_type: Override the forecasting engine model ("baseline" or "ml").
                        Defaults to settings.FORECAST_MODEL.
        """
        self._default_provider = default_provider
        self._model_type = model_type

    async def forecast_demand(self, request: ForecastRequest) -> DemandForecast:
        """Produce a DemandForecast for the given request."""
        forecast, _ = await self.forecast_demand_with_explanation(request)
        return forecast

    async def forecast_demand_with_explanation(
        self,
        request: ForecastRequest,
    ) -> tuple[DemandForecast, ForecastExplanation]:
        """
        Produce a DemandForecast along with its structured explainability report.

        Errors propagate explicitly:
            - InsufficientDataError → HTTP 422
            - InvalidObservationError → HTTP 422
            - ProviderUnavailableError → HTTP 503
            - ForecastCalculationError → HTTP 500
        """
        started = time.perf_counter()
        provider = self._select_provider(request.observations, request.target_service)
        observations: List[DemandObservation] = provider.get_observations(
            window_seconds=request.historical_window_seconds or 3600
        )

        effective_model = (self._model_type or settings.FORECAST_MODEL).lower()

        if effective_model in ("ml", "demand-ml-v1"):
            ml_engine = MLDemandForecaster(ridge_alpha=settings.ML_RIDGE_ALPHA)
            forecast = ml_engine.predict(
                observations=observations,
                forecast_horizon_seconds=request.forecast_horizon_seconds,
                trace_id=request.trace_id,
            )
        else:
            forecast = produce_forecast(
                observations=observations,
                forecast_horizon_seconds=request.forecast_horizon_seconds,
                trace_id=request.trace_id,
            )

        explanation = ForecastExplainer.explain(forecast, observations)

        logger.info(
            "Demand forecast generated",
            extra={
                "provider": provider.name,
                "model_version": forecast.model_version,
                "observation_count": len(observations),
                "forecast_horizon_seconds": request.forecast_horizon_seconds,
                "trace_id": forecast.trace_id,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "explanation_tags": explanation.all_tags,
                "quality_rating": explanation.quality_tag,
            },
        )
        return forecast, explanation

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
