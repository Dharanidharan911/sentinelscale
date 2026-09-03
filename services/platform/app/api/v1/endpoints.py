from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from app.models.context import DecisionContext, PolicyOverrides
from app.models.decision import ScalingDecision
from app.models.resource import ResourceState
from app.services.context_aggregator import AggregationError, ContextAggregatorService
from app.services.decision_engine import DecisionEngine
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.factory import get_telemetry_provider

router = APIRouter(tags=["Platform & Resource Intelligence"])


class OrchestrationRequest(BaseModel):
    namespace: str = Field(default="sentinelscale", description="Target Kubernetes namespace.")
    workload: str = Field(default="demo-api", description="Target workload / Deployment name.")
    window_seconds: int = Field(default=60, ge=1, description="Observation time window for Traffic Intelligence.")
    forecast_horizon_seconds: int = Field(default=300, ge=1, description="Forecasting horizon for Demand Intelligence.")
    policy_overrides: Optional[PolicyOverrides] = Field(default=None, description="Optional runtime policy constraints.")


def get_resource_observer(
    provider: ResourceTelemetryProvider = Depends(get_telemetry_provider)
) -> ResourceObserverService:
    return ResourceObserverService(provider=provider)


def get_decision_engine() -> DecisionEngine:
    return DecisionEngine()


def get_context_aggregator(
    observer: ResourceObserverService = Depends(get_resource_observer),
    engine: DecisionEngine = Depends(get_decision_engine),
) -> ContextAggregatorService:
    return ContextAggregatorService(
        resource_observer=observer,
        decision_engine=engine,
    )


@router.get("/resources/current", response_model=ResourceState)
async def get_current_resources(
    namespace: str = Query(default="sentinelscale", description="Kubernetes namespace"),
    workload: str = Query(default="demo-api", description="Workload/Deployment name"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
    observer: ResourceObserverService = Depends(get_resource_observer),
) -> ResourceState:
    """
    Retrieve real-time resource utilization and capacity state for a target workload.
    """
    try:
        return await observer.get_current_resource_state(
            namespace=namespace,
            workload=workload,
            trace_id=x_trace_id
        )
    except TelemetryProviderError as err:
        raise HTTPException(
            status_code=502,
            detail=f"Telemetry Provider Failure: {err.message}"
        ) from err


@router.post("/decision/evaluate", response_model=ScalingDecision)
async def evaluate_decision(
    context: DecisionContext,
    engine: DecisionEngine = Depends(get_decision_engine),
) -> ScalingDecision:
    """
    Direct evaluation: Evaluate a scaling decision from a pre-constructed DecisionContext.
    Calculates security-aware recommendation, baseline HPA comparison,
    and enforces safety guardrails in dry-run mode.
    Preserved for backward compatibility and deterministic replays.
    """
    return await engine.evaluate_decision(context)


@router.post("/decision/orchestrate", response_model=ScalingDecision)
async def orchestrate_decision(
    request: OrchestrationRequest = OrchestrationRequest(),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
    aggregator: ContextAggregatorService = Depends(get_context_aggregator),
) -> ScalingDecision:
    """
    Phase 3B Orchestration: Concurrently queries Traffic Intelligence (Module 1),
    Demand Intelligence (Module 2), and Resource State (Module 3), constructs a canonical
    DecisionContext, and executes the deterministic DecisionEngine to return a ScalingDecision.
    """
    try:
        return await aggregator.orchestrate_decision(
            namespace=request.namespace,
            workload=request.workload,
            window_seconds=request.window_seconds,
            forecast_horizon_seconds=request.forecast_horizon_seconds,
            policy_overrides=request.policy_overrides,
            trace_id=x_trace_id,
        )
    except AggregationError as agg_err:
        raise HTTPException(
            status_code=502,
            detail=f"Decision Orchestration Failure: [{agg_err.source}] {agg_err.message}",
        ) from agg_err
    except TelemetryProviderError as tel_err:
        raise HTTPException(
            status_code=502,
            detail=f"Telemetry Provider Failure: {tel_err.message}",
        ) from tel_err


@router.post("/decision/aggregate", response_model=DecisionContext)
async def aggregate_decision_context(
    request: OrchestrationRequest = OrchestrationRequest(),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
    aggregator: ContextAggregatorService = Depends(get_context_aggregator),
) -> DecisionContext:
    """
    Phase 3B Context Aggregation: Concurrently queries Traffic Intelligence, Demand Intelligence,
    and Resource State, and returns the aggregated, schema-compliant DecisionContext without evaluation.
    """
    try:
        return await aggregator.aggregate_context(
            namespace=request.namespace,
            workload=request.workload,
            window_seconds=request.window_seconds,
            forecast_horizon_seconds=request.forecast_horizon_seconds,
            policy_overrides=request.policy_overrides,
            trace_id=x_trace_id,
        )
    except AggregationError as agg_err:
        raise HTTPException(
            status_code=502,
            detail=f"Decision Context Aggregation Failure: [{agg_err.source}] {agg_err.message}",
        ) from agg_err
    except TelemetryProviderError as tel_err:
        raise HTTPException(
            status_code=502,
            detail=f"Telemetry Provider Failure: {tel_err.message}",
        ) from tel_err
