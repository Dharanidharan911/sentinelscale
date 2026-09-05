"""
SentinelScale — Scenario Runner
Orchestrates: ScenarioDefinition → AsyncTrafficGenerator → TelemetryCollector → Module 1 Assessment.
"""
import time
import uuid
from typing import Optional
import httpx
from pydantic import BaseModel, Field

from app.harness.collector import TelemetryCollector
from app.harness.generator import AsyncTrafficGenerator
from app.harness.models import ScenarioDefinition, TrafficScenarioType, create_scenario_preset
from app.models.traffic_contract import AssessmentRequest, TrafficAssessment, TrafficTelemetryInput


class ScenarioExecutionResult(BaseModel):
    """Encapsulates the complete end-to-end outcome of a generated traffic scenario."""
    scenario_name: str
    scenario_type: TrafficScenarioType
    trace_id: str
    total_requests_generated: int
    duration_seconds: float
    observed_telemetry: TrafficTelemetryInput
    assessment: TrafficAssessment
    execution_latency_ms: float


class ScenarioRunner:
    """
    End-to-end executor for Stage F1 traffic scenarios.
    Ensures zero fabrication: traffic is generated, measured empirically, and assessed by M1.
    """

    def __init__(
        self,
        demo_api_url: str = "http://demo-api:8000",
        traffic_intelligence_url: str = "http://traffic-intelligence:8001",
        demo_api_client: Optional[httpx.AsyncClient] = None,
        traffic_client: Optional[httpx.AsyncClient] = None,
    ):
        self.demo_api_url = demo_api_url.rstrip("/")
        self.traffic_intelligence_url = traffic_intelligence_url.rstrip("/")
        self._demo_client = demo_api_client
        self._traffic_client = traffic_client

    async def run_scenario(
        self,
        scenario: ScenarioDefinition,
        rate_limit_pacing: bool = False,
    ) -> ScenarioExecutionResult:
        """
        Execute full lifecycle:
        1. Generate HTTP traffic against demo-api.
        2. Observe and aggregate request events into TrafficTelemetryInput.
        3. Dispatch TrafficTelemetryInput to Module 1 (/api/v1/traffic/assess).
        4. Validate returned TrafficAssessment against frozen schema.
        """
        start_time = time.perf_counter()
        trace_id = scenario.trace_id or f"trace-{uuid.uuid4().hex[:16]}"
        scenario.trace_id = trace_id

        # 1. Generate HTTP traffic
        generator = AsyncTrafficGenerator(
            base_url=self.demo_api_url,
            client=self._demo_client,
        )
        events = await generator.generate_traffic(scenario, rate_limit_pacing=rate_limit_pacing)

        # 2. Collect empirical telemetry
        window_seconds = int(scenario.duration_seconds)
        telemetry = TelemetryCollector.collect(
            events=events,
            window_seconds=window_seconds,
            baseline_rps=scenario.baseline_rps,
        )

        # 3. Invoke Module 1 Traffic Intelligence
        assessment = await self._invoke_traffic_intelligence(
            telemetry=telemetry,
            window_seconds=window_seconds,
            trace_id=trace_id,
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return ScenarioExecutionResult(
            scenario_name=scenario.name,
            scenario_type=scenario.scenario_type,
            trace_id=trace_id,
            total_requests_generated=len(events),
            duration_seconds=scenario.duration_seconds,
            observed_telemetry=telemetry,
            assessment=assessment,
            execution_latency_ms=elapsed_ms,
        )

    async def _invoke_traffic_intelligence(
        self,
        telemetry: TrafficTelemetryInput,
        window_seconds: int,
        trace_id: str,
    ) -> TrafficAssessment:
        """Call POST /api/v1/traffic/assess with the empirical telemetry payload."""
        endpoint_url = f"{self.traffic_intelligence_url}/api/v1/traffic/assess"
        headers = {"X-Trace-ID": trace_id}
        payload = {
            "window_seconds": window_seconds,
            "target_service": "demo-api",
            "trace_id": trace_id,
            "telemetry": telemetry.model_dump(),
        }

        client = self._traffic_client or httpx.AsyncClient(timeout=10.0)
        close_client = self._traffic_client is None

        try:
            resp = await client.post(endpoint_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return TrafficAssessment.model_validate(data)
        finally:
            if close_client:
                await client.aclose()

