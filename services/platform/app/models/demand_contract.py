from typing import List, Optional
from pydantic import BaseModel, Field


class DemandObservation(BaseModel):
    """
    A single time-series observation of legitimate RPS at a point in time.
    Supplied to Module 2 Demand Intelligence for time-series forecasting.
    """
    timestamp: float = Field(
        ...,
        description="Unix epoch timestamp (seconds, UTC) of this observation."
    )
    rps: float = Field(
        ...,
        ge=0.0,
        description="Observed requests per second (legitimate demand) at this timestamp."
    )


class ForecastRequest(BaseModel):
    """
    Outbound request payload to Module 2 (Demand Intelligence).
    """
    forecast_horizon_seconds: int = Field(
        default=300,
        ge=1,
        description="Forecasting horizon forward in seconds."
    )
    target_service: Optional[str] = Field(
        default="demo-api",
        description="Target service identifier."
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Optional upstream distributed trace ID."
    )
    historical_window_seconds: Optional[int] = Field(
        default=3600,
        ge=60,
        description="Telemetry history lookback window in seconds."
    )
    observations: Optional[List[DemandObservation]] = Field(
        default=None,
        description="Optional historical demand observation series."
    )


class DemandForecast(BaseModel):
    event_id: str
    trace_id: str
    generated_at: str
    contract_version: str
    service_version: str
    model_version: str
    forecast_horizon_seconds: int
    predicted_legitimate_rps: float
    lower_bound_rps: float
    upper_bound_rps: float
    confidence: float = Field(..., ge=0.0, le=1.0)
