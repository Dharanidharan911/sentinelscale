from enum import Enum
from pydantic import BaseModel, Field


class ScalingAction(str, Enum):
    SCALE = "SCALE"
    RATE_LIMIT = "RATE_LIMIT"
    MITIGATE = "MITIGATE"
    HOLD = "HOLD"


class ScalingDecision(BaseModel):
    decision_id: str = Field(..., description="Unique decision UUID.")
    event_id: str = Field(..., description="Triggering event UUID.")
    trace_id: str = Field(..., description="Distributed tracing identifier.")
    timestamp: str = Field(..., description="ISO-8601 generation timestamp.")
    contract_version: str = Field(..., pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    service_version: str = Field(..., description="Platform service version.")
    model_version: str = Field(..., description="Policy rule engine version.")
    action: ScalingAction = Field(..., description="Recommended infrastructure action.")
    reason: str = Field(..., description="Deterministic decision explanation.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Composite confidence score.")
    traffic_risk: float = Field(..., ge=0.0, le=1.0, description="Evaluated traffic risk.")
    predicted_legitimate_rps: float = Field(..., ge=0.0, description="Predicted legitimate demand.")
    current_capacity_rps: float = Field(..., ge=0.0, description="Current cluster capacity.")
    current_pods: int = Field(..., ge=0, description="Current replica count.")
    recommended_pods: int = Field(..., ge=0, description="Recommended replica count.")
    baseline_hpa_recommended_pods: int = Field(..., ge=0, description="Standard reactive HPA recommendation.")
    pod_delta_vs_baseline: int = Field(..., description="Difference: recommended_pods - baseline_hpa_pods.")
    policy: str = Field(..., description="Enforced policy guardrail name.")
    dry_run: bool = Field(default=True, description="Safety flag: recommendation only.")
    shadow_mode: bool = Field(default=True, description="Shadow mode flag.")
