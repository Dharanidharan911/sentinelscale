from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from app.models.context import DecisionContext
from app.models.decision import ScalingDecision
from app.models.resource import ResourceState
from app.services.decision_engine import DecisionEngine
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.factory import get_telemetry_provider

router = APIRouter(tags=["Platform & Resource Intelligence"])


def get_resource_observer(
    provider: ResourceTelemetryProvider = Depends(get_telemetry_provider)
) -> ResourceObserverService:
    return ResourceObserverService(provider=provider)


def get_decision_engine() -> DecisionEngine:
    return DecisionEngine()


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
    Evaluate a scaling decision from a structured DecisionContext.
    Calculates security-aware recommendation, baseline HPA comparison,
    and enforces safety guardrails in dry-run mode.
    """
    return await engine.evaluate_decision(context)
