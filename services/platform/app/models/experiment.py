from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ExperimentPhase(BaseModel):
    phase_name: str = Field(..., description="Name of the experiment lifecycle phase.")
    timestamp: str = Field(..., description="ISO8601 timestamp of phase transition.")
    elapsed_seconds: float = Field(..., ge=0, description="Elapsed seconds since experiment start.")


class WorkloadSummary(BaseModel):
    total_requests: int = Field(..., ge=0, description="Total HTTP requests generated during trial.")
    average_rps: float = Field(..., ge=0, description="Average requests per second.")
    peak_rps: float = Field(..., ge=0, description="Peak requests per second observed.")
    error_rate: float = Field(..., ge=0, le=1.0, description="Fraction of failed requests (0.0 - 1.0).")
    p50_latency_ms: float = Field(..., ge=0, description="50th percentile response latency in milliseconds.")
    p95_latency_ms: float = Field(..., ge=0, description="95th percentile response latency in milliseconds.")


class HpaSummary(BaseModel):
    initial_replicas: int = Field(..., ge=1, description="Initial Kubernetes HPA replica count.")
    final_replicas: int = Field(..., ge=1, description="Final Kubernetes HPA replica count.")
    peak_replicas: int = Field(..., ge=1, description="Peak Kubernetes HPA replica count.")
    min_replicas: int = Field(..., ge=1, description="Minimum Kubernetes HPA replica count.")
    scale_up_events_count: Optional[int] = Field(default=0, ge=0, description="Count of HPA scale-up events.")
    scale_down_events_count: Optional[int] = Field(default=0, ge=0, description="Count of HPA scale-down events.")
    scale_up_latency_seconds: Optional[float] = Field(default=None, description="Latency to first scale-up in seconds.")
    scale_down_latency_seconds: Optional[float] = Field(default=None, description="Latency to first scale-down in seconds.")
    pod_seconds: float = Field(..., ge=0, description="Cumulative pod-seconds consumed by HPA.")
    replica_hours: float = Field(..., ge=0, description="Cumulative replica-hours consumed by HPA.")


class SentinelScaleSummary(BaseModel):
    initial_recommended_pods: int = Field(..., ge=1, description="Initial recommended replica count.")
    final_recommended_pods: int = Field(..., ge=1, description="Final recommended replica count.")
    peak_recommended_pods: int = Field(..., ge=1, description="Peak recommended replica count.")
    min_recommended_pods: int = Field(..., ge=1, description="Minimum recommended replica count.")
    pod_seconds: float = Field(..., ge=0, description="Cumulative recommended pod-seconds.")
    replica_hours: float = Field(..., ge=0, description="Cumulative recommended replica-hours.")
    decisions_count: int = Field(..., ge=0, description="Total evaluation decision cycles recorded.")
    action_distribution: Dict[str, int] = Field(default_factory=dict, description="Frequency map of scaling actions.")


class ComparisonSummary(BaseModel):
    pod_seconds_delta: float = Field(..., description="SentinelScale pod-seconds minus HPA pod-seconds (negative = savings).")
    replica_hours_delta: float = Field(..., description="SentinelScale replica-hours minus HPA replica-hours (negative = savings).")
    max_replica_difference: int = Field(..., description="Maximum absolute replica delta observed in trial.")
    divergence_classification: Literal["agreement", "sentinelscale_recommends_fewer", "sentinelscale_recommends_more", "mixed"] = Field(
        ..., description="Categorization of comparative behavior."
    )
    performance_guardrails_passed: bool = Field(..., description="Whether both p95 latency and error rate met safety limits.")


class PerformanceGuardrails(BaseModel):
    p95_latency_guardrail_ms: float = Field(..., ge=0, description="Maximum allowable p95 latency in ms.")
    observed_p95_latency_ms: float = Field(..., ge=0, description="Empirically observed p95 latency in ms.")
    error_rate_guardrail: float = Field(..., ge=0, le=1.0, description="Maximum allowable error rate fraction.")
    observed_error_rate: float = Field(..., ge=0, le=1.0, description="Empirically observed error rate fraction.")
    guardrails_passed: bool = Field(..., description="Whether all performance guardrails passed.")


class ExperimentSafety(BaseModel):
    dry_run: bool = Field(default=True, description="Strict safety invariant: dry run execution.")
    shadow_mode: bool = Field(default=True, description="Strict safety invariant: shadow mode.")
    sentinel_mutations_count: int = Field(default=0, description="Strict safety invariant: 0 cluster mutations.")
    autonomous_actions_enabled: bool = Field(default=False, description="Strict safety invariant: autonomous actions disabled.")


class ExperimentTimeseriesPoint(BaseModel):
    timestamp: str = Field(..., description="ISO8601 timestamp of data point.")
    elapsed_seconds: float = Field(..., ge=0, description="Elapsed seconds since experiment trial start.")
    request_rate: Optional[float] = Field(default=None, description="Observed request rate in RPS.")
    cpu_utilization: Optional[float] = Field(default=None, description="Observed CPU utilization fraction.")
    hpa_replicas: int = Field(..., ge=1, description="Current HPA replica count.")
    hpa_desired_replicas: int = Field(..., ge=1, description="Desired HPA replica count calculated by reactive HPA.")
    hpa_cpu_percent: Optional[float] = Field(default=None, description="Observed HPA target metric percentage.")
    sentinelscale_recommended_pods: int = Field(..., ge=1, description="SentinelScale recommended pods.")
    replica_delta: int = Field(..., description="Difference: SentinelScale recommended minus HPA replicas.")
    sentinelscale_action: Optional[str] = Field(default=None, description="Action recommended by SentinelScale.")
    decision_reason: Optional[str] = Field(default=None, description="Explanatory rationale for the decision.")


class ExperimentResult(BaseModel):
    """Canonical model for M3-8 comparative experiment results conforming to experiment_result.schema.json."""
    run_id: str = Field(..., description="Unique identifier for this experiment trial.")
    scenario_id: str = Field(..., description="Scenario configuration identifier.")
    scenario_name: str = Field(..., description="Human-readable scenario name.")
    start_time: str = Field(..., description="ISO8601 experiment start timestamp.")
    end_time: str = Field(..., description="ISO8601 experiment end timestamp.")
    duration_seconds: float = Field(..., ge=0, description="Total duration of experiment trial in seconds.")
    phases: List[ExperimentPhase] = Field(default_factory=list, description="Lifecycle phases of the trial.")
    workload_summary: WorkloadSummary = Field(..., description="Aggregated workload traffic summary.")
    hpa_summary: HpaSummary = Field(..., description="Aggregated HPA behavior summary.")
    sentinelscale_summary: SentinelScaleSummary = Field(..., description="Aggregated SentinelScale behavior summary.")
    comparison_summary: ComparisonSummary = Field(..., description="Aggregated comparative analysis summary.")
    performance_guardrails: PerformanceGuardrails = Field(..., description="Validation against performance guardrails.")
    safety: ExperimentSafety = Field(default_factory=ExperimentSafety, description="Safety invariant audit verification.")
    timeseries: List[ExperimentTimeseriesPoint] = Field(default_factory=list, description="High-resolution time-series observations.")


class ExperimentRunSummary(BaseModel):
    """Lightweight summary model for listing experiment trials without loading complete timeseries payloads."""
    run_id: str = Field(..., description="Unique identifier for this experiment trial.")
    scenario_id: str = Field(..., description="Scenario configuration identifier.")
    scenario_name: str = Field(..., description="Human-readable scenario name.")
    start_time: str = Field(..., description="ISO8601 experiment start timestamp.")
    end_time: str = Field(..., description="ISO8601 experiment end timestamp.")
    duration_seconds: float = Field(..., ge=0, description="Total duration of experiment trial in seconds.")
    workload_summary: WorkloadSummary = Field(..., description="Aggregated workload traffic summary.")
    hpa_summary: HpaSummary = Field(..., description="Aggregated HPA behavior summary.")
    sentinelscale_summary: SentinelScaleSummary = Field(..., description="Aggregated SentinelScale behavior summary.")
    comparison_summary: ComparisonSummary = Field(..., description="Aggregated comparative analysis summary.")
    performance_guardrails: PerformanceGuardrails = Field(..., description="Validation against performance guardrails.")
    safety: ExperimentSafety = Field(default_factory=ExperimentSafety, description="Safety invariant audit verification.")
    has_timeseries: bool = Field(default=True, description="Whether timeseries data is available in the detailed record.")

