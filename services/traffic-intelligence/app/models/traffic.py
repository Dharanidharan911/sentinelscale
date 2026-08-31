from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, UUID4, field_validator


class TrafficClassification(str, Enum):
    LEGITIMATE = "legitimate"
    SUSPICIOUS = "suspicious"
    MALICIOUS = "malicious"
    UNKNOWN = "unknown"


class AssessmentRequest(BaseModel):
    window_seconds: int = Field(default=60, ge=1, description="Observation time window duration in seconds.")
    target_service: Optional[str] = Field(default="demo-api", description="Target service identifier.")
    trace_id: Optional[str] = Field(default=None, description="Optional upstream trace ID.")


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


class ServiceInfo(BaseModel):
    service: str
    version: str
    status: str
