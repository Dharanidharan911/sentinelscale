import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Header, Query
from app.config.settings import settings
from app.models.context import DecisionContext
from app.models.decision import ScalingDecision
from app.models.resource import ResourceState
from app.mock.generator import MockResourceDataGenerator
from app.services.decision_engine import DecisionEngine
from app.services.resource_observer import ResourceObserverService
from app.clients.traffic_client import TrafficIntelligenceClient
from app.clients.demand_client import DemandIntelligenceClient

router = APIRouter(tags=["Platform & Resource Intelligence"])


def get_resource_observer() -> ResourceObserverService:
    return ResourceObserverService()


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
    return await observer.get_current_resource_state(
        namespace=namespace,
        workload=workload,
        trace_id=x_trace_id
    )


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
