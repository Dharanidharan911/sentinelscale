import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from app.clients.demand_client import DemandIntelligenceClient, UpstreamDemandIntelligenceError
from app.clients.traffic_client import TrafficIntelligenceClient, UpstreamTrafficIntelligenceError
from app.config.settings import settings
from app.logging import logger
from app.models.context import DecisionContext, PolicyOverrides
from app.models.decision import ScalingDecision
from app.models.demand_contract import DemandForecast
from app.models.resource import ResourceState
from app.models.traffic_contract import TrafficAssessment
from app.services.decision_engine import DecisionEngine
from app.services.history import DemandObservationAccumulator, get_demand_accumulator
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.base import TelemetryProviderError
from app.telemetry.tracing import create_span


class AggregationError(Exception):
    """
    Raised when DecisionContext aggregation fails due to upstream intelligence
    unreachability, timeout, or contract validation failure.
    """

    def __init__(self, source: str, message: str, original_error: Optional[Exception] = None):
        self.source = source
        self.message = message
        self.original_error = original_error
        super().__init__(f"[{source}] {message}")


class ContextAggregatorService:
    """
    Production-oriented Decision Context Aggregation & Orchestration Service.
    Concurrently coordinates:
      1. Traffic Intelligence (Module 1) -> TrafficAssessment
      2. Demand Intelligence (Module 2) -> DemandForecast
      3. Resource Observer (Module 3) -> ResourceState
    Constructs a validated DecisionContext and invokes the deterministic DecisionEngine.
    """

    def __init__(
        self,
        traffic_client: Optional[TrafficIntelligenceClient] = None,
        demand_client: Optional[DemandIntelligenceClient] = None,
        resource_observer: Optional[ResourceObserverService] = None,
        decision_engine: Optional[DecisionEngine] = None,
        demand_accumulator: Optional[DemandObservationAccumulator] = None,
    ):
        self.traffic_client = traffic_client or TrafficIntelligenceClient()
        self.demand_client = demand_client or DemandIntelligenceClient()
        self.resource_observer = resource_observer or ResourceObserverService()
        self.decision_engine = decision_engine or DecisionEngine()
        self.demand_accumulator = demand_accumulator or get_demand_accumulator()

    async def aggregate_context(
        self,
        namespace: str = "sentinelscale",
        workload: str = "demo-api",
        window_seconds: int = 60,
        forecast_horizon_seconds: int = 300,
        policy_overrides: Optional[PolicyOverrides] = None,
        trace_id: Optional[str] = None,
    ) -> DecisionContext:
        """
        Concurrently collects TrafficAssessment, DemandForecast, and ResourceState,
        correlates them under a unified trace_id, and constructs a typed DecisionContext.
        Explicitly raises AggregationError on any upstream dependency failure.
        """
        resolved_trace_id = trace_id or f"trace-{uuid.uuid4().hex[:16]}"
        start_time = time.perf_counter()

        logger.info(
            f"Starting decision context aggregation for workload '{namespace}/{workload}'",
            extra={"trace_id": resolved_trace_id, "service": "platform"},
        )

        with create_span(
            "context_aggregator.aggregate_context",
            attributes={
                "namespace": namespace,
                "workload": workload,
                "trace_id": resolved_trace_id,
                "window_seconds": window_seconds,
                "forecast_horizon_seconds": forecast_horizon_seconds,
            }
        ) as span:
            # Retrieve accumulated historical demand observations for target workload
            historical_observations = None
            if self.demand_accumulator:
                historical_observations = self.demand_accumulator.get_historical_demand_observations(
                    target_service=workload,
                    historical_window_seconds=settings.DEMAND_OBSERVATION_HISTORY_WINDOW_SECONDS,
                )

            # Concurrently fetch from all 3 intelligence streams
            results = await asyncio.gather(
                self.traffic_client.fetch_assessment(
                    window_seconds=window_seconds,
                    trace_id=resolved_trace_id,
                ),
                self.demand_client.fetch_forecast(
                    forecast_horizon_seconds=forecast_horizon_seconds,
                    trace_id=resolved_trace_id,
                    target_service=workload,
                    historical_window_seconds=settings.DEMAND_OBSERVATION_HISTORY_WINDOW_SECONDS,
                    observations=historical_observations if historical_observations else None,
                ),
                self.resource_observer.get_current_resource_state(
                    namespace=namespace,
                    workload=workload,
                    trace_id=resolved_trace_id,
                ),
                return_exceptions=True,
            )

            traffic_res, demand_res, resource_res = results

            # Inspect failures with strict error provenance
            if isinstance(traffic_res, Exception):
                logger.error(
                    f"Aggregation failed: Traffic Intelligence error: {traffic_res}",
                    extra={"trace_id": resolved_trace_id, "service": "platform"},
                )
                if isinstance(traffic_res, UpstreamTrafficIntelligenceError):
                    raise AggregationError(
                        source="Traffic Intelligence",
                        message=traffic_res.message,
                        original_error=traffic_res,
                    ) from traffic_res
                raise AggregationError(
                    source="Traffic Intelligence",
                    message=str(traffic_res),
                    original_error=traffic_res,
                ) from traffic_res

            if isinstance(demand_res, Exception):
                logger.error(
                    f"Aggregation failed: Demand Intelligence error: {demand_res}",
                    extra={"trace_id": resolved_trace_id, "service": "platform"},
                )
                if isinstance(demand_res, UpstreamDemandIntelligenceError):
                    raise AggregationError(
                        source="Demand Intelligence",
                        message=demand_res.message,
                        original_error=demand_res,
                    ) from demand_res
                raise AggregationError(
                    source="Demand Intelligence",
                    message=str(demand_res),
                    original_error=demand_res,
                ) from demand_res

            if isinstance(resource_res, Exception):
                logger.error(
                    f"Aggregation failed: Resource Intelligence error: {resource_res}",
                    extra={"trace_id": resolved_trace_id, "service": "platform"},
                )
                if isinstance(resource_res, TelemetryProviderError):
                    raise AggregationError(
                        source="Resource Intelligence",
                        message=resource_res.message,
                        original_error=resource_res,
                    ) from resource_res
                raise AggregationError(
                    source="Resource Intelligence",
                    message=str(resource_res),
                    original_error=resource_res,
                ) from resource_res

            # All 3 streams succeeded - construct canonical DecisionContext
            context_id = str(uuid.uuid4())
            timestamp = datetime.now(timezone.utc).isoformat()
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

            context = DecisionContext(
                context_id=context_id,
                trace_id=resolved_trace_id,
                timestamp=timestamp,
                contract_version=settings.CONTRACT_VERSION,
                target_workload=workload,
                traffic_assessment=traffic_res,
                demand_forecast=demand_res,
                resource_state=resource_res,
                policy_overrides=policy_overrides,
                dry_run=settings.SENTINEL_DRY_RUN,
                shadow_mode=settings.SENTINEL_SHADOW_MODE,
            )

            if span:
                span.set_attribute("context.id", context_id)
                span.set_attribute("context.latency_ms", latency_ms)

            logger.info(
                f"Successfully aggregated DecisionContext '{context_id}' in {latency_ms}ms",
                extra={
                    "trace_id": resolved_trace_id,
                    "context_id": context_id,
                    "latency_ms": latency_ms,
                    "service": "platform",
                },
            )

            return context

    async def orchestrate_decision(
        self,
        namespace: str = "sentinelscale",
        workload: str = "demo-api",
        window_seconds: int = 60,
        forecast_horizon_seconds: int = 300,
        policy_overrides: Optional[PolicyOverrides] = None,
        trace_id: Optional[str] = None,
    ) -> ScalingDecision:
        """
        Full end-to-end orchestration:
          1. Aggregates real DecisionContext from upstream intelligence
          2. Evaluates scaling recommendation through DecisionEngine
          3. Applies policy guardrails and shadow-mode comparisons
          4. Returns deterministic ScalingDecision
        """
        resolved_trace_id = trace_id or f"trace-{uuid.uuid4().hex[:16]}"
        with create_span(
            "context_aggregator.orchestrate_decision",
            attributes={
                "namespace": namespace,
                "workload": workload,
                "trace_id": resolved_trace_id,
            }
        ) as span:
            context = await self.aggregate_context(
                namespace=namespace,
                workload=workload,
                window_seconds=window_seconds,
                forecast_horizon_seconds=forecast_horizon_seconds,
                policy_overrides=policy_overrides,
                trace_id=resolved_trace_id,
            )

            decision = await self.decision_engine.evaluate_decision(context)

            if span:
                span.set_attribute("decision.id", decision.decision_id)
                span.set_attribute("decision.action", decision.action.value)
                span.set_attribute("decision.recommended_pods", decision.recommended_pods)

            logger.info(
                f"Orchestrated decision: Action={decision.action.value}, "
                f"RecommendedPods={decision.recommended_pods}, "
                f"BaselineHPAPods={decision.baseline_hpa_recommended_pods}, "
                f"PodDelta={decision.pod_delta_vs_baseline}",
                extra={
                    "trace_id": context.trace_id,
                    "decision_id": decision.decision_id,
                    "action": decision.action.value,
                    "service": "platform",
                },
            )

            return decision
