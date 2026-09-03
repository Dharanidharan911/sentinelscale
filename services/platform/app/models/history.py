from typing import Optional
from pydantic import BaseModel, Field
from app.models.decision import ScalingAction


class StoredObservation(BaseModel):
    """
    Durable representation of a single SentinelScale observation evaluation cycle.
    Preserves audit fidelity, queryable indicators, and full JSON payloads for replay.
    """
    id: str = Field(..., description="Unique observation/evaluation UUID.")
    trace_id: str = Field(..., description="Distributed correlation trace identifier.")
    timestamp: str = Field(..., description="ISO-8601 timestamp when observation was initiated.")
    completed_at: Optional[str] = Field(default=None, description="ISO-8601 timestamp when observation completed.")
    duration_ms: float = Field(default=0.0, description="Evaluation execution duration in milliseconds.")
    success: bool = Field(..., description="Whether the observation completed successfully.")

    # Queryable scaling metrics & decisions (populated if success=True)
    action: Optional[ScalingAction] = Field(default=None, description="Evaluated scaling recommendation action.")
    reason: Optional[str] = Field(default=None, description="Detailed explanation of the scaling decision.")
    confidence: Optional[float] = Field(default=None, description="Composite confidence score.")
    recommended_pods: Optional[int] = Field(default=None, description="SentinelScale recommended replicas.")
    current_pods: Optional[int] = Field(default=None, description="Current running replicas.")
    baseline_hpa_recommended_pods: Optional[int] = Field(default=None, description="Reactive HPA recommendation.")
    pod_delta_vs_baseline: Optional[int] = Field(default=None, description="Replicas difference vs reactive HPA.")
    traffic_risk: Optional[float] = Field(default=None, description="Assessed traffic security risk score.")
    predicted_legitimate_rps: Optional[float] = Field(default=None, description="Predicted legitimate workload RPS.")
    current_capacity_rps: Optional[float] = Field(default=None, description="Current cluster capacity in RPS.")
    policy: Optional[str] = Field(default=None, description="Applied safety policy guardrail.")
    dry_run: bool = Field(default=True, description="Enforced dry-run safety invariant.")
    shadow_mode: bool = Field(default=True, description="Enforced shadow-mode safety invariant.")

    # Failure diagnostics (populated if success=False)
    error_type: Optional[str] = Field(default=None, description="Category/type of upstream or pipeline failure.")
    error_message: Optional[str] = Field(default=None, description="Detailed failure diagnostics.")

    # Canonical full JSON payloads for replay foundation & audit fidelity
    scaling_decision_json: Optional[str] = Field(default=None, description="Full JSON serialized ScalingDecision.")
    error_details_json: Optional[str] = Field(default=None, description="Detailed error diagnostics JSON.")


class HistoryStats(BaseModel):
    """Aggregated statistics of the observation history store."""
    total_observations: int = Field(..., description="Total recorded observation cycles.")
    successful_observations: int = Field(..., description="Total successful observation cycles.")
    failed_observations: int = Field(..., description="Total failed observation cycles.")
    retention_days: int = Field(..., description="Configured retention period in days.")

