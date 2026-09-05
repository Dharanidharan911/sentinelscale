"""
SentinelScale — Demand Intelligence — API v1 Endpoints
Exposes the Demand Intelligence contract to Member 3 and integration consumers.

Route: POST /api/v1/demand/forecast
Contract: DemandForecast v1.0.0

Error mapping:
  InsufficientDataError    → 422 Unprocessable Entity
  InvalidObservationError  → 422 Unprocessable Entity
  ProviderUnavailableError → 503 Service Unavailable
  Unexpected errors        → 500 Internal Server Error

IMPORTANT: errors are NEVER silently converted to zero demand.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse

from app.models.demand import DemandForecast, ForecastRequest
from app.services.forecaster import DemandForecastingService
from app.errors import (
    InsufficientDataError,
    InvalidObservationError,
    ProviderUnavailableError,
    ForecastCalculationError,
)

router = APIRouter(prefix="/demand", tags=["Demand Intelligence"])


def get_forecaster_service() -> DemandForecastingService:
    return DemandForecastingService()


@router.post(
    "/forecast",
    response_model=DemandForecast,
    summary="Generate Demand Forecast",
    description=(
        "Produce a future legitimate workload demand forecast (DemandForecast v1.0.0). "
        "Optionally supply demand observations in the request body; "
        "if omitted the service uses its internal mock/telemetry provider. "
        "Trace IDs propagate from the X-Trace-ID header or request body field."
    ),
    responses={
        200: {"description": "DemandForecast produced successfully."},
        422: {"description": "Insufficient or invalid demand data."},
        503: {"description": "Demand data provider unavailable."},
        500: {"description": "Unexpected internal forecasting error."},
    },
)
async def forecast_demand(
    request: ForecastRequest,
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
    service: DemandForecastingService = Depends(get_forecaster_service),
) -> DemandForecast:
    # Trace ID: request body takes precedence over header; header is fallback
    if x_trace_id and not request.trace_id:
        request.trace_id = x_trace_id

    try:
        return await service.forecast_demand(request)

    except InsufficientDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "insufficient_data",
                "message": str(exc),
                "required_samples": exc.required,
                "available_samples": exc.available,
            },
        )

    except InvalidObservationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_observation",
                "message": str(exc),
            },
        )

    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "provider_unavailable",
                "provider": exc.provider_name,
                "message": str(exc),
            },
        )

    except ForecastCalculationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "forecast_calculation_error",
                "message": str(exc),
            },
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "message": f"Unexpected error in demand forecasting: {type(exc).__name__}",
            },
        )
