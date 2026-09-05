from enum import Enum
from typing import List
from pydantic import BaseModel, Field


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
    total_requests: int = Field(..., ge=0, description="Total requests observed in window.")
    total_rps: float = Field(..., ge=0.0, description="Observed requests per second.")
    baseline_rps: float | None = Field(default=None, ge=0.0, description="Expected baseline RPS for this window.")
    status_codes: StatusCodeDistribution | None = Field(default=None, description="HTTP status code counts.")
    top_ip_ratio: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Proportion of requests coming from top IP or top 3 IPs."
    )
    unique_ip_count: int | None = Field(default=None, ge=0, description="Number of unique client IPs.")
    non_standard_ua_ratio: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Proportion of requests with bot/empty/abnormal User-Agents."
    )
    single_endpoint_ratio: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Proportion of requests targeting a single endpoint."
    )


class AssessmentRequest(BaseModel):
    window_seconds: int = Field(default=60, ge=1, description="Observation time window duration in seconds.")
    target_service: str | None = Field(default="demo-api", description="Target service identifier.")
    trace_id: str | None = Field(default=None, description="Optional upstream trace ID.")
    telemetry: TrafficTelemetryInput | None = Field(
        default=None, description="Optional telemetry input for deterministic evaluation."
    )


class TrafficAssessment(BaseModel):
    event_id: str
    trace_id: str
    timestamp: str
    contract_version: str
    service_version: str
    model_version: str
    window_seconds: int
    total_rps: float
    legitimate_rps_estimate: float
    suspicious_rps_estimate: float
    risk_score: float = Field(..., ge=0.0, le=1.0)
    legitimacy_score: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    classification: TrafficClassification
    top_signals: List[str]
