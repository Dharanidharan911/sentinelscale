from pydantic import BaseModel, Field


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
