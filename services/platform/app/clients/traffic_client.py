import time
from typing import Optional
import httpx
from pydantic import ValidationError
from app.config.settings import settings
from app.logging import logger
from app.models.traffic_contract import TrafficAssessment
from app.telemetry.tracing import inject_trace_context, create_span


class UpstreamTrafficIntelligenceError(Exception):
    """Raised when communication with Module 1 (Traffic Intelligence) fails."""

    def __init__(self, message: str, status_code: Optional[int] = None, original_error: Optional[Exception] = None):
        self.message = message
        self.status_code = status_code
        self.original_error = original_error
        super().__init__(f"[TrafficIntelligenceClient] {message}")


class TrafficIntelligenceClient:
    """HTTP Client for communicating with Module 1 (Traffic Intelligence)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = (base_url or settings.TRAFFIC_INTELLIGENCE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or 5.0
        self._custom_client = http_client

    async def fetch_assessment(
        self,
        window_seconds: int = 60,
        trace_id: Optional[str] = None,
    ) -> TrafficAssessment:
        endpoint_url = f"{self.base_url}/api/v1/traffic/assess"
        headers = {"X-Trace-ID": trace_id} if trace_id else {}
        headers = inject_trace_context(headers)
        payload = {"window_seconds": window_seconds, "trace_id": trace_id}

        client = self._custom_client or httpx.AsyncClient(timeout=self.timeout_seconds)
        close_client = self._custom_client is None
        start_time = time.perf_counter()

        with create_span(
            "traffic_intelligence.fetch_assessment",
            attributes={
                "http.method": "POST",
                "http.url": endpoint_url,
                "window_seconds": window_seconds,
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
                        f"Traffic Intelligence error: HTTP {response.status_code}",
                        extra={
                            "trace_id": trace_id,
                            "endpoint": endpoint_url,
                            "status_code": response.status_code,
                            "latency_ms": latency_ms,
                        },
                    )
                    raise UpstreamTrafficIntelligenceError(
                        message=f"HTTP {response.status_code} received from {endpoint_url}: {response.text[:200]}",
                        status_code=response.status_code,
                    )

                try:
                    data = response.json()
                except Exception as json_err:
                    raise UpstreamTrafficIntelligenceError(
                        message=f"Malformed JSON in response from {endpoint_url}: {str(json_err)}",
                        original_error=json_err,
                    ) from json_err

                try:
                    assessment = TrafficAssessment.model_validate(data)
                    return assessment
                except ValidationError as val_err:
                    raise UpstreamTrafficIntelligenceError(
                        message=f"TrafficAssessment contract validation failed: {val_err.errors()}",
                        original_error=val_err,
                    ) from val_err

            except httpx.TimeoutException as timeout_err:
                raise UpstreamTrafficIntelligenceError(
                    message=f"Request to Traffic Intelligence timed out after {self.timeout_seconds}s at {endpoint_url}",
                    original_error=timeout_err,
                ) from timeout_err
            except httpx.RequestError as req_err:
                raise UpstreamTrafficIntelligenceError(
                    message=f"Network error communicating with Traffic Intelligence at {endpoint_url}: {str(req_err)}",
                    original_error=req_err,
                ) from req_err
            finally:
                if close_client:
                    await client.aclose()
