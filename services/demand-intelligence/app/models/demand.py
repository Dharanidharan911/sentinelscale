from typing import Optional
from pydantic import BaseModel, Field


class ForecastRequest(BaseModel):
    forecast_horizon_seconds: int = Field(default=300, ge=1, description="Forecasting horizon forward in seconds.")
    target_service: Optional[str] = Field(default="demo-api", description="Target service identifier.")
    trace_id: Optional[str] = Field(default=None, description="Optional upstream distributed trace ID.")
    historical_window_seconds: Optional[int] = Field(default=3600, ge=60, description="Telemetry history lookback.")


class DemandForecast(BaseModel):
    event_id: str = Field(..., description="Unique forecast event UUID.")
    trace_id: str = Field(..., description="Distributed tracing identifier.")
    generated_at: str = Field(..., description="ISO-8601 generation timestamp.")
    contract_version: str = Field(..., pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", description="Semantic contract version.")
    service_version: str = Field(..., description="Demand Intelligence service version.")
    model_version: str = Field(..., description="Demand forecast model version.")
    forecast_horizon_seconds: int = Field(..., ge=1, description="Forecast horizon duration.")
    predicted_legitimate_rps: float = Field(..., ge=0.0, description="Predicted legitimate RPS.")
    lower_bound_rps: float = Field(..., ge=0.0, description="Lower prediction interval bound.")
    upper_bound_rps: float = Field(..., ge=0.0, description="Upper prediction interval bound.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Forecast confidence score.")
