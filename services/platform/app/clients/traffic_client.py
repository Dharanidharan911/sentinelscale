import httpx
from typing import Optional
from app.config.settings import settings
from app.models.traffic_contract import TrafficAssessment


class TrafficIntelligenceClient:
    """HTTP Client for communicating with Module 1 (Traffic Intelligence)."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.TRAFFIC_INTELLIGENCE_URL).rstrip("/")

    async def fetch_assessment(
        self,
        window_seconds: int = 60,
        trace_id: Optional[str] = None
    ) -> TrafficAssessment:
        async with httpx.AsyncClient(timeout=5.0) as client:
            headers = {"X-Trace-ID": trace_id} if trace_id else {}
            response = await client.post(
                f"{self.base_url}/api/v1/traffic/assess",
                json={"window_seconds": window_seconds, "trace_id": trace_id},
                headers=headers
            )
            response.raise_for_status()
            return TrafficAssessment.model_validate(response.json())
