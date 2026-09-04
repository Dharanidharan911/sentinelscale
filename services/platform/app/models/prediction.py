from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PredictionStatus(str, Enum):
    OK = "OK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    DEGRADED = "DEGRADED"
    STALE = "STALE"


class TrendDirection(str, Enum):
    INCREASING = "INCREASING"
    DECREASING = "DECREASING"
    STABLE = "STABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ConfidenceLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class PressureLevel(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DataQuality(str, Enum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class SignalForecast(BaseModel):
    """Deterministic forecast for a single operational metric signal."""
    signal: str = Field(..., description="Name of the forecasted operational signal.")
    status: PredictionStatus = Field(..., description="Forecast status for this signal.")
    sample_count: int = Field(..., description="Number of historical samples used in trend fitting.")
    latest_value: Optional[float] = Field(default=None, description="Most recent observed value.")
    predicted_value: Optional[float] = Field(default=None, description="Forecasted value at the target horizon.")
    delta: Optional[float] = Field(default=None, description="Signed projected change (predicted - latest).")
    delta_percent: Optional[float] = Field(default=None, description="Percentage projected change relative to latest.")
    trend: TrendDirection = Field(..., description="Classified trend direction.")
    confidence: ConfidenceLevel = Field(..., description="Deterministic forecast confidence level.")
    mean: Optional[float] = Field(default=None, description="Sample arithmetic mean in lookback window.")
    slope_per_second: Optional[float] = Field(default=None, description="Linear trend slope per second.")
    forecast_horizon_seconds: int = Field(..., description="Horizon in seconds for this projection.")
    interpretation: Optional[str] = Field(default=None, description="Human-readable interpretation of the forecast.")


class PredictivePressure(BaseModel):
    """Forecasted infrastructure capacity pressure and workload headroom."""
    predicted_legitimate_rps: Optional[float] = Field(default=None, description="Forecasted legitimate demand RPS.")
    predicted_capacity_rps: Optional[float] = Field(default=None, description="Forecasted cluster processing capacity RPS.")
    predicted_capacity_utilization: Optional[float] = Field(default=None, description="Predicted ratio of demand to capacity.")
    level: PressureLevel = Field(..., description="Categorized capacity pressure level.")
    interpretation: str = Field(..., description="Human-readable capacity pressure assessment.")


class PredictivePodAdvisory(BaseModel):
    """Advisory replica requirements and comparative HPA forecast."""
    predicted_recommended_pods: Optional[int] = Field(default=None, description="Advisory recommended replicas for forecast demand.")
    predicted_hpa_pods: Optional[int] = Field(default=None, description="Forecasted reactive HPA recommendation.")
    predicted_delta_vs_hpa: Optional[int] = Field(default=None, description="Forecasted replica difference (SentinelScale - HPA).")
    min_pods: int = Field(default=2, description="Guaranteed minimum replica boundary.")
    max_pods: int = Field(default=20, description="Guaranteed maximum replica boundary.")
    interpretation: str = Field(..., description="Advisory interpretation comparing SentinelScale and HPA forecasts.")


class PredictiveForecast(BaseModel):
    """Complete predictive intelligence report across operational signals, capacity pressure, and advisory replicas."""
    generated_at: str = Field(..., description="ISO-8601 timestamp when forecast was generated.")
    baseline_window: Optional[str] = Field(default=None, description="Lookback historical window used (e.g. 15m, 1h).")
    start_time: str = Field(..., description="ISO-8601 start timestamp of lookback window.")
    end_time: str = Field(..., description="ISO-8601 end timestamp of lookback window.")
    forecast_horizon_seconds: int = Field(..., description="Projection horizon in seconds.")
    status: PredictionStatus = Field(..., description="Overall predictive intelligence status.")
    data_quality: DataQuality = Field(..., description="Evaluated historical data quality state.")
    sample_count: int = Field(..., description="Total valid observation samples analyzed.")
    minimum_required_samples: int = Field(default=5, description="Minimum samples required for forecasting.")
    latest_observation_time: Optional[str] = Field(default=None, description="Timestamp of the most recent observation analyzed.")
    signals: Dict[str, SignalForecast] = Field(default_factory=dict, description="Per-signal forecasts.")
    pressure: PredictivePressure = Field(..., description="Predicted capacity utilization and pressure.")
    pods: PredictivePodAdvisory = Field(..., description="Advisory pod requirement projection.")
    explanation: str = Field(..., description="Executive summary of predictive findings.")

