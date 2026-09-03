from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class TrafficClassification(str, Enum):
    LEGITIMATE = "legitimate"
    SUSPICIOUS = "suspicious"
    MALICIOUS = "malicious"
    UNKNOWN = "unknown"


class StatusCodeDistribution(BaseModel):
    status_2xx: int = Field(default=0, ge=0, description="Count of 2xx successful responses.")
    status_3xx: int = Field(default=0, ge=0, description="Count of 3xx redirection responses.")
    status_4xx: int = Field(default=0, ge=0, description="Count of 4xx client error responses.")
    status_5xx: int = Field(default=0, ge=0, description="Count of 5xx server error responses.")

    @property
    def total_requests(self) -> int:
        return self.status_2xx + self.status_3xx + self.status_4xx + self.status_5xx

    @property
    def error_rate(self) -> float:
        total = self.total_requests
        if total == 0:
            return 0.0
        return (self.status_4xx + self.status_5xx) / total


class TrafficTelemetryInput(BaseModel):
    """
    Detailed telemetry input for fine-grained traffic assessment.
    Can be supplied directly by telemetry collectors or simulated in tests.
    """
    total_requests: int = Field(..., ge=0, description="Total requests observed in window.")
    total_rps: float = Field(..., ge=0.0, description="Observed requests per second.")
    baseline_rps: Optional[float] = Field(default=None, ge=0.0, description="Expected baseline RPS for this window.")
    status_codes: Optional[StatusCodeDistribution] = Field(default=None, description="HTTP status code counts.")
    top_ip_ratio: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Proportion of requests coming from top IP or top 3 IPs."
    )
    unique_ip_count: Optional[int] = Field(default=None, ge=0, description="Number of unique client IPs.")
    non_standard_ua_ratio: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Proportion of requests with bot/empty/abnormal User-Agents."
    )
    single_endpoint_ratio: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Proportion of requests targeting a single endpoint."
    )

    @model_validator(mode="after")
    def validate_rates(self) -> "TrafficTelemetryInput":
        if self.baseline_rps is not None and self.baseline_rps < 0.0:
            raise ValueError("baseline_rps must be non-negative")
        return self


class AssessmentRequest(BaseModel):
    window_seconds: int = Field(default=60, ge=1, description="Observation time window duration in seconds.")
    target_service: Optional[str] = Field(default="demo-api", description="Target service identifier.")
    trace_id: Optional[str] = Field(default=None, description="Optional upstream trace ID.")
    telemetry: Optional[TrafficTelemetryInput] = Field(
        default=None, description="Optional telemetry input for deterministic evaluation."
    )


class TrafficAssessment(BaseModel):
    event_id: str = Field(..., description="Unique assessment event UUID.")
    trace_id: str = Field(..., description="Distributed tracing identifier.")
    timestamp: str = Field(..., description="ISO-8601 evaluation timestamp.")
    contract_version: str = Field(..., pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", description="Semantic contract version.")
    service_version: str = Field(..., description="Traffic Intelligence service version.")
    model_version: str = Field(..., description="Traffic model version.")
    window_seconds: int = Field(..., ge=1, description="Observation window duration.")
    total_rps: float = Field(..., ge=0.0, description="Total observed RPS.")
    legitimate_rps_estimate: float = Field(..., ge=0.0, description="Estimated legitimate RPS.")
    suspicious_rps_estimate: float = Field(..., ge=0.0, description="Estimated suspicious RPS.")
    risk_score: float = Field(..., ge=0.0, le=1.0, description="Security risk probability.")
    legitimacy_score: float = Field(..., ge=0.0, le=1.0, description="Traffic legitimacy score.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score.")
    classification: TrafficClassification = Field(..., description="Traffic categorization.")
    top_signals: List[str] = Field(..., description="Detected behavioral signals.")

    model_config = {"extra": "forbid"}


class ServiceInfo(BaseModel):
    service: str
    version: str
    status: str
