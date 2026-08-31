from enum import Enum
from typing import List
from pydantic import BaseModel, Field


class TrafficClassification(str, Enum):
    LEGITIMATE = "legitimate"
    SUSPICIOUS = "suspicious"
    MALICIOUS = "malicious"
    UNKNOWN = "unknown"


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
