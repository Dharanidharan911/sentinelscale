import time
from typing import List, Optional
import httpx
from pydantic import ValidationError
from app.config.settings import settings
from app.logging import logger
from app.models.demand_contract import DemandForecast, DemandObservation
from app.telemetry.tracing import inject_trace_context, create_span


class UpstreamDemandIntelligenceError(Exception):
    """Raised when communication with Module 2 (Demand Intelligence) fails."""

    def __init__(self, message: str, status_code: Optional[int] = None, original_error: Optional[Exception] = None):
        self.message = message
        self.status_code = status_code
        self.original_error = original_error
        super().__init__(f"[DemandIntelligenceClient] {message}")


class DemandIntelligenceClient:
    """HTTP Client for communicating with Module 2 (Demand Intelligence)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = (base_url or settings.DEMAND_INTELLIGENCE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or 5.0
        self._custom_client = http_client

    async def fetch_forecast(
        self,
        forecast_horizon_seconds: int = 300,
        trace_id: Optional[str] = None,
        target_service: Optional[str] = "demo-api",
        historical_window_seconds: Optional[int] = 3600,
        observations: Optional[list[DemandObservation]] = None,
    ) -> DemandForecast:
        endpoint_url = f"{self.base_url}/api/v1/demand/forecast"
        headers = {"X-Trace-ID": trace_id} if trace_id else {}
        headers = inject_trace_context(headers)
        payload = {
            "forecast_horizon_seconds": forecast_horizon_seconds,
            "target_service": target_service,
            "trace_id": trace_id,
            "historical_window_seconds": historical_window_seconds,
        }
        if observations is not None:
            payload["observations"] = [obs.model_dump() for obs in observations]

        client = self._custom_client or httpx.AsyncClient(timeout=self.timeout_seconds)
        close_client = self._custom_client is None
        start_time = time.perf_counter()

        with create_span(
            "demand_intelligence.fetch_forecast",
            attributes={
                "http.method": "POST",
                "http.url": endpoint_url,
                "forecast_horizon_seconds": forecast_horizon_seconds,
                "target_service": target_service or "",
                "trace_id": trace_id or "",
            }
        ) as span:
            try:
                response = await client.post(endpoint_url, json=payload, headers=headers)
                latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
                if span:
                    span.set_attribute("http.status_code", response.status_code)

                if response.status_code != 200:
                    logger.error(
                        f"Demand Intelligence error: HTTP {response.status_code}",
                        extra={
                            "trace_id": trace_id,
                            "endpoint": endpoint_url,
                            "status_code": response.status_code,
                            "latency_ms": latency_ms,
                        },
                    )
                    raise UpstreamDemandIntelligenceError(
                        message=f"HTTP {response.status_code} received from {endpoint_url}: {response.text[:200]}",
                        status_code=response.status_code,
                    )

                try:
                    data = response.json()
                except Exception as json_err:
                    raise UpstreamDemandIntelligenceError(
                        message=f"Malformed JSON in response from {endpoint_url}: {str(json_err)}",
                        original_error=json_err,
                    ) from json_err

                try:
                    forecast = DemandForecast.model_validate(data)
                    return forecast
                except ValidationError as val_err:
                    raise UpstreamDemandIntelligenceError(
                        message=f"DemandForecast contract validation failed: {val_err.errors()}",
                        original_error=val_err,
                    ) from val_err

            except httpx.TimeoutException as timeout_err:
                raise UpstreamDemandIntelligenceError(
                    message=f"Request to Demand Intelligence timed out after {self.timeout_seconds}s at {endpoint_url}",
                    original_error=timeout_err,
                ) from timeout_err
            except httpx.RequestError as req_err:
                raise UpstreamDemandIntelligenceError(
                    message=f"Network error communicating with Demand Intelligence at {endpoint_url}: {str(req_err)}",
                    original_error=req_err,
                ) from req_err
            finally:
                if close_client:
                    await client.aclose()
