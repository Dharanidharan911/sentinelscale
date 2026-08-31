from fastapi import APIRouter, Depends, Header
from typing import Optional
from app.models.traffic import AssessmentRequest, TrafficAssessment
from app.services.assessor import TrafficAssessmentService

router = APIRouter(prefix="/traffic", tags=["Traffic Intelligence"])


def get_assessor_service() -> TrafficAssessmentService:
    return TrafficAssessmentService()


@router.post("/assess", response_model=TrafficAssessment)
async def assess_traffic(
    request: AssessmentRequest,
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
    service: TrafficAssessmentService = Depends(get_assessor_service),
) -> TrafficAssessment:
    """
    Assess incoming API traffic behaviour, security risk, and legitimacy.
    Currently backed by deterministic mock implementation (traffic-v0).
    """
    if x_trace_id and not request.trace_id:
        request.trace_id = x_trace_id
    return await service.assess_traffic(request)
