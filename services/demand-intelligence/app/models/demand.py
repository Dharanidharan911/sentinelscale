"""
SentinelScale — Demand Intelligence — Domain Models
Module 2 public and internal data contracts.
"""
import math
import time
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from app.config.settings import settings


class DemandObservation(BaseModel):
    """
    A single time-series observation of legitimate RPS at a point in time.
    Used as input to the forecasting engine.
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

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_positive(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("timestamp must be finite")
        if v <= 0:
            raise ValueError("timestamp must be a positive Unix epoch value")
        if v > time.time() + settings.OBSERVATION_MAX_FUTURE_SKEW_SECONDS:
            raise ValueError("timestamp is too far in the future")
        return v

    @field_validator("rps")
    @classmethod
    def rps_must_be_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("rps must be finite")
        return v


class ForecastRequest(BaseModel):
    """
    Input to the Demand Intelligence forecast endpoint.
    Observations are optional; if not provided, the service uses its internal
    mock / telemetry provider.
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
        description=(
            "Optional explicit list of demand observations. "
            "If supplied, the service uses these instead of the internal provider. "
            "Enables Member 3 and integration tests to supply real or synthetic data directly."
        )
    )


class DemandForecast(BaseModel):
    """
    Output contract for Module 2 (Demand Intelligence).
    Schema is frozen at contract_version 1.0.0.
    Do not modify required fields or types without a contract version bump.
    """
    event_id: str = Field(..., description="Unique forecast event UUID.")
    trace_id: str = Field(..., description="Distributed tracing identifier.")
    generated_at: str = Field(..., description="ISO-8601 generation timestamp.")
    contract_version: str = Field(
        ...,
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$",
        description="Semantic contract version."
    )
    service_version: str = Field(..., description="Demand Intelligence service version.")
    model_version: str = Field(..., description="Demand forecast model version.")
    forecast_horizon_seconds: int = Field(..., ge=1, description="Forecast horizon duration.")
    predicted_legitimate_rps: float = Field(..., ge=0.0, description="Predicted legitimate RPS.")
    lower_bound_rps: float = Field(..., ge=0.0, description="Lower prediction interval bound.")
    upper_bound_rps: float = Field(..., ge=0.0, description="Upper prediction interval bound.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Forecast confidence score.")
