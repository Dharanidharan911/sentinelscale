import httpx
from typing import Optional
from app.config.settings import settings
from app.models.demand_contract import DemandForecast


class DemandIntelligenceClient:
    """HTTP Client for communicating with Module 2 (Demand Intelligence)."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.DEMAND_INTELLIGENCE_URL).rstrip("/")

    async def fetch_forecast(
        self,
        forecast_horizon_seconds: int = 300,
        trace_id: Optional[str] = None
    ) -> DemandForecast:
        async with httpx.AsyncClient(timeout=5.0) as client:
            headers = {"X-Trace-ID": trace_id} if trace_id else {}
            response = await client.post(
                f"{self.base_url}/api/v1/demand/forecast",
                json={"forecast_horizon_seconds": forecast_horizon_seconds, "trace_id": trace_id},
                headers=headers
            )
            response.raise_for_status()
            return DemandForecast.model_validate(response.json())
