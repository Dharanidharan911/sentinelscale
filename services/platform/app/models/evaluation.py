from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class EvaluationCategory(str, Enum):
    ALIGNED = "ALIGNED"
    SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE = "SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE"
    SENTINELSCALE_PROACTIVELY_SCALES = "SENTINELSCALE_PROACTIVELY_SCALES"
    SCALE_DOWN_DIFFERENCE = "SCALE_DOWN_DIFFERENCE"
    UNCERTAIN = "UNCERTAIN"


class RecommendationDifference(str, Enum):
    EQUAL = "EQUAL"
    SENTINELSCALE_FEWER_PODS = "SENTINELSCALE_FEWER_PODS"
    SENTINELSCALE_MORE_PODS = "SENTINELSCALE_MORE_PODS"


class EvaluationMetrics(BaseModel):
    replica_delta: int = Field(
        ...,
        description="Signed replica difference: sentinelscale_recommended_pods - hpa_recommended_pods."
    )
    absolute_replica_delta: int = Field(
        ...,
        ge=0,
        description="Absolute value of replica delta."
    )
    estimated_pod_hours_saved_per_hour: float = Field(
        ...,
        ge=0.0,
        description="Estimated pod-hours saved per running hour by avoiding unnecessary scaling."
    )
    estimated_cpu_cores_saved: Optional[float] = Field(
        default=None,
        description="Estimated CPU cores saved per hour (if per-pod CPU limits or metrics are known)."
    )
    unnecessary_scale_up_signal: bool = Field(
        ...,
        description="True if HPA would scale up on attack traffic while legitimate demand is within capacity."
    )
    capacity_satisfied: bool = Field(
        ...,
        description="True if predicted legitimate demand is less than or equal to current capacity."
    )
    suppression_reason: Optional[str] = Field(
        default=None,
        description="Specific reason explaining scaling suppression if applicable."
    )


class EvaluationResult(BaseModel):
    evaluation_id: str = Field(..., description="Unique evaluation identifier UUID.")
    trace_id: str = Field(..., description="Distributed tracing identifier.")
    timestamp: str = Field(..., description="ISO-8601 generation timestamp.")
    category: EvaluationCategory = Field(
        ...,
        description="Primary categorization of the HPA vs SentinelScale comparison."
    )
    recommendation_difference: RecommendationDifference = Field(
        ...,
        description="Directional difference between recommendations."
    )
    explanation: str = Field(
        ...,
        description="Deterministic, human-readable rationale explaining the comparative divergence."
    )
    hpa_recommended_pods: int = Field(
        ...,
        ge=0,
        description="Pods recommended by reactive Kubernetes HPA baseline."
    )
    sentinelscale_recommended_pods: int = Field(
        ...,
        ge=0,
        description="Pods recommended by security-aware SentinelScale engine."
    )
    current_pods: int = Field(
        ...,
        ge=0,
        description="Current replica count in the cluster."
    )
    traffic_risk: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Evaluated traffic risk score [0.0, 1.0]."
    )
    predicted_legitimate_rps: float = Field(
        ...,
        ge=0.0,
        description="Predicted legitimate demand RPS."
    )
    current_capacity_rps: float = Field(
        ...,
        ge=0.0,
        description="Current cluster capacity in RPS."
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Composite confidence score of the evaluation input."
    )
    metrics: EvaluationMetrics = Field(
        ...,
        description="Quantitative metrics and structural cost savings."
    )
    dry_run: bool = Field(
        default=True,
        description="Safety invariant: read-only evaluation."
    )
    shadow_mode: bool = Field(
        default=True,
        description="Shadow mode indicator."
    )

