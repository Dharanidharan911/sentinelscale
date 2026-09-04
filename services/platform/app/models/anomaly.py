from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class AnomalySeverity(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    ANOMALOUS = "ANOMALOUS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class SignalDirection(str, Enum):
    HIGHER_THAN_BASELINE = "HIGHER_THAN_BASELINE"
    LOWER_THAN_BASELINE = "LOWER_THAN_BASELINE"
    NEAR_BASELINE = "NEAR_BASELINE"


class MetricBaseline(BaseModel):
    """Historical reference statistics for a single metric signal."""
    metric: str = Field(..., description="Name of the evaluated metric signal.")
    sample_count: int = Field(..., description="Number of historical samples evaluated.")
    mean: float = Field(..., description="Arithmetic mean of baseline samples.")
    stddev: float = Field(..., description="Population standard deviation.")
    min_value: float = Field(..., description="Minimum observed historical value.")
    max_value: float = Field(..., description="Maximum observed historical value.")
    median: Optional[float] = Field(default=None, description="Median historical value.")


class AnomalySignal(BaseModel):
    """Anomaly evaluation for an individual metric signal against its historical baseline."""
    metric: str = Field(..., description="Name of the evaluated metric signal.")
    current_value: float = Field(..., description="Observed current value.")
    baseline_mean: Optional[float] = Field(default=None, description="Historical baseline mean.")
    baseline_stddev: Optional[float] = Field(default=None, description="Historical baseline standard deviation.")
    deviation: Optional[float] = Field(default=None, description="Signed deviation (current - mean).")
    z_score: Optional[float] = Field(default=None, description="Calculated standard z-score.")
    severity: AnomalySeverity = Field(..., description="Assessed anomaly severity level.")
    direction: SignalDirection = Field(..., description="Direction of deviation relative to baseline.")
    sample_count: int = Field(..., description="Number of baseline samples used.")
    interpretation: Optional[str] = Field(default=None, description="Domain-aware interpretation of the signal.")


class AnomalyAssessment(BaseModel):
    """Comprehensive anomaly assessment comparing current observations to behavioral baselines."""
    generated_at: str = Field(..., description="ISO-8601 timestamp when assessment was generated.")
    baseline_window: Optional[str] = Field(default=None, description="Time window evaluated for baseline (e.g. 1h, 24h).")
    start_time: str = Field(..., description="ISO-8601 start timestamp of baseline window.")
    end_time: str = Field(..., description="ISO-8601 end timestamp of baseline window.")
    sample_count: int = Field(..., description="Total historical observation samples in baseline window.")
    minimum_required_samples: int = Field(default=5, description="Minimum samples required for baseline significance.")
    overall_severity: AnomalySeverity = Field(..., description="Composite anomaly severity classification.")
    anomalous_signal_count: int = Field(default=0, description="Count of signals classified as ANOMALOUS.")
    elevated_signal_count: int = Field(default=0, description="Count of signals classified as ELEVATED.")
    signals: List[AnomalySignal] = Field(default_factory=list, description="Per-metric anomaly signals.")
    explanation: str = Field(..., description="Human-readable explanation of behavioral findings.")
    pattern_notes: Optional[List[str]] = Field(default=None, description="Domain-specific pattern observations.")

