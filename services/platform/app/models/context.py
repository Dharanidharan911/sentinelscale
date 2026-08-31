from typing import Optional
from pydantic import BaseModel, Field
from app.models.traffic_contract import TrafficAssessment
from app.models.demand_contract import DemandForecast
from app.models.resource import ResourceState


class PolicyOverrides(BaseModel):
    min_pods: Optional[int] = Field(default=None, ge=1)
    max_pods: Optional[int] = Field(default=None, ge=1)
    target_cpu_utilization: Optional[float] = Field(default=None, ge=0.1, le=1.0)
    pod_rps_capacity: Optional[float] = Field(default=None, ge=1.0)


class DecisionContext(BaseModel):
    context_id: str = Field(..., description="Unique context identifier.")
    trace_id: str = Field(..., description="Distributed tracing identifier.")
    timestamp: str = Field(..., description="ISO-8601 timestamp.")
    contract_version: str = Field(..., pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    target_workload: str = Field(..., description="Workload deployment name.")
    traffic_assessment: TrafficAssessment = Field(..., description="Assessment from Module 1.")
    demand_forecast: DemandForecast = Field(..., description="Forecast from Module 2.")
    resource_state: ResourceState = Field(..., description="Observed resource & telemetry state.")
    policy_overrides: Optional[PolicyOverrides] = Field(default=None)
    dry_run: bool = Field(default=True, description="Enforce recommendation-only dry run mode.")
    shadow_mode: bool = Field(default=True, description="Enable baseline HPA comparison.")
