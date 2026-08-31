from fastapi import APIRouter, Depends, Header
from typing import Optional
from app.models.demand import DemandForecast, ForecastRequest
from app.services.forecaster import DemandForecastingService

router = APIRouter(prefix="/demand", tags=["Demand Intelligence"])


def get_forecaster_service() -> DemandForecastingService:
    return DemandForecastingService()


@router.post("/forecast", response_model=DemandForecast)
async def forecast_demand(
    request: ForecastRequest,
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
    service: DemandForecastingService = Depends(get_forecaster_service),
) -> DemandForecast:
    """
    Generate future legitimate workload demand forecast.
    Currently backed by deterministic mock implementation (demand-v0).
    """
    if x_trace_id and not request.trace_id:
        request.trace_id = x_trace_id
    return await service.forecast_demand(request)
