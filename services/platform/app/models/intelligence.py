from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class TimeRangeInfo(BaseModel):
    """Metadata describing the historical analysis time window."""
    start_time: str = Field(..., description="ISO-8601 formatted start timestamp.")
    end_time: str = Field(..., description="ISO-8601 formatted end timestamp.")
    window: Optional[str] = Field(default=None, description="Pre-defined time window name if supplied (e.g. 1h, 24h).")


class ObservationCountStats(BaseModel):
    """Observation frequency and success statistics."""
    total_observations: int = Field(..., description="Total observation cycles recorded in the window.")
    successful_observations: int = Field(..., description="Count of successfully evaluated observations.")
    failed_observations: int = Field(..., description="Count of failed/errored observations.")
    success_rate: float = Field(..., ge=0.0, le=1.0, description="Ratio of successful observations to total.")


class DecisionDistributionStats(BaseModel):
    """Distribution of decision actions and specialized scenarios."""
    scale_events: int = Field(..., description="Count of SCALE decisions.")
    hold_events: int = Field(..., description="Count of HOLD decisions.")
    rate_limit_events: int = Field(default=0, description="Count of RATE_LIMIT decisions.")
    scale_down_events: int = Field(default=0, description="Count of decisions where recommended_pods < current_pods.")
    hold_under_high_risk_events: int = Field(default=0, description="Count of HOLD decisions occurring under high traffic risk.")
    legitimate_demand_scale_events: int = Field(default=0, description="Count of SCALE decisions driven by legitimate demand.")


class DemandHistoricalStats(BaseModel):
    """Demand forecasting historical statistics."""
    average_predicted_legitimate_rps: Optional[float] = Field(default=None, description="Average predicted legitimate RPS.")
    peak_predicted_legitimate_rps: Optional[float] = Field(default=None, description="Peak predicted legitimate RPS.")
    min_predicted_legitimate_rps: Optional[float] = Field(default=None, description="Minimum predicted legitimate RPS.")


class TrafficRiskHistoricalStats(BaseModel):
    """Traffic risk assessment historical statistics."""
    average_traffic_risk: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Average security risk score.")
    peak_traffic_risk: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Peak security risk score.")
    high_risk_observations: int = Field(default=0, description="Count of observations with traffic risk >= 0.70.")


class CapacityHistoricalStats(BaseModel):
    """Observed infrastructure capacity statistics."""
    average_current_capacity_rps: Optional[float] = Field(default=None, description="Average cluster capacity in RPS.")


class PodRecommendationStats(BaseModel):
    """Pod recommendation and running replica statistics."""
    average_recommended_pods: Optional[float] = Field(default=None, description="Mean recommended replicas.")
    average_current_pods: Optional[float] = Field(default=None, description="Mean observed running replicas.")
    max_recommended_pods: Optional[int] = Field(default=None, description="Maximum recommended replicas.")
    min_recommended_pods: Optional[int] = Field(default=None, description="Minimum recommended replicas.")


class HpaComparisonStats(BaseModel):
    """SentinelScale vs Reactive HPA baseline comparative analytics."""
    hpa_scale_events: int = Field(default=0, description="Count of observations where baseline HPA would scale up.")
    sentinelscale_scale_events: int = Field(default=0, description="Count of observations where SentinelScale scaled up.")
    comparable_observations: int = Field(..., description="Count of successful observations with HPA baseline data.")
    agreement_count: int = Field(..., description="Count of observations where SentinelScale pods == HPA pods.")
    divergence_count: int = Field(..., description="Count of observations where SentinelScale pods != HPA pods.")
    agreement_rate: float = Field(..., ge=0.0, le=1.0, description="Proportion of observations where recommendations matched.")
    divergence_rate: float = Field(..., ge=0.0, le=1.0, description="Proportion of observations where recommendations diverged.")
    average_hpa_divergence: float = Field(..., description="Mean signed divergence (SentinelScale pods - HPA pods).")
    max_hpa_divergence: int = Field(..., description="Maximum absolute pod difference vs reactive HPA.")
    positive_divergence_count: int = Field(default=0, description="Observations where SentinelScale recommended MORE pods than HPA.")
    negative_divergence_count: int = Field(default=0, description="Observations where SentinelScale recommended FEWER pods than HPA (suppressed overprovisioning).")


class DecisionQualityStats(BaseModel):
    """Composite historical decision quality and reliability indicators."""
    decision_success_rate: float = Field(..., ge=0.0, le=1.0, description="Observation pipeline success rate.")
    decision_failure_rate: float = Field(..., ge=0.0, le=1.0, description="Observation pipeline failure rate.")
    sentinelscale_vs_hpa_agreement_rate: float = Field(..., ge=0.0, le=1.0, description="Agreement rate vs naive HPA.")
    sentinelscale_vs_hpa_divergence_rate: float = Field(..., ge=0.0, le=1.0, description="Divergence rate vs naive HPA.")
    hold_under_high_risk_frequency: float = Field(default=0.0, ge=0.0, le=1.0, description="Frequency of attack mitigation HOLD actions.")
    legitimate_demand_scale_frequency: float = Field(default=0.0, ge=0.0, le=1.0, description="Frequency of legitimate demand scale-up actions.")
    scale_down_frequency: float = Field(default=0.0, ge=0.0, le=1.0, description="Frequency of scale-down actions.")
    upstream_failure_frequency: Dict[str, int] = Field(default_factory=dict, description="Distribution of upstream/pipeline failure types.")


class HistoricalSummary(BaseModel):
    """Complete summary of historical observations and scaling analytics for a time range."""
    time_range: TimeRangeInfo
    observation_counts: ObservationCountStats
    decision_distribution: DecisionDistributionStats
    demand_stats: DemandHistoricalStats
    traffic_risk_stats: TrafficRiskHistoricalStats
    capacity_stats: CapacityHistoricalStats
    pod_stats: PodRecommendationStats
    hpa_comparison: HpaComparisonStats
    decision_quality: DecisionQualityStats


class TrendBucket(BaseModel):
    """Chronological time-bucketed historical aggregation for trend visualization."""
    bucket_start: str = Field(..., description="ISO-8601 start timestamp of the bucket.")
    bucket_end: str = Field(..., description="ISO-8601 end timestamp of the bucket.")
    total_observations: int = Field(default=0, description="Total observations in bucket.")
    successful_observations: int = Field(default=0, description="Successful observations in bucket.")
    failed_observations: int = Field(default=0, description="Failed observations in bucket.")
    average_predicted_legitimate_rps: Optional[float] = Field(default=None, description="Average predicted legitimate demand.")
    average_traffic_risk: Optional[float] = Field(default=None, description="Average traffic security risk score.")
    average_current_capacity_rps: Optional[float] = Field(default=None, description="Average capacity in RPS.")
    average_recommended_pods: Optional[float] = Field(default=None, description="Mean recommended replicas.")
    average_baseline_hpa_pods: Optional[float] = Field(default=None, description="Mean baseline HPA replicas.")
    average_divergence: Optional[float] = Field(default=None, description="Mean signed replica divergence.")
    scale_count: int = Field(default=0, description="SCALE decisions in bucket.")
    hold_count: int = Field(default=0, description="HOLD decisions in bucket.")
    rate_limit_count: int = Field(default=0, description="RATE_LIMIT decisions in bucket.")


class HistoricalTrends(BaseModel):
    """Time-series buckets of historical observations."""
    time_range: TimeRangeInfo
    bucket_interval_seconds: int = Field(..., description="Duration of each bucket in seconds.")
    total_buckets: int = Field(..., description="Total number of buckets.")
    buckets: List[TrendBucket] = Field(default_factory=list, description="Chronological trend buckets.")


class HistoricalDivergence(BaseModel):
    """Detailed historical comparison and divergence breakdown against reactive HPA baseline."""
    time_range: TimeRangeInfo
    comparable_observations: int = Field(..., description="Number of observations with baseline HPA comparison data.")
    agreement_count: int = Field(..., description="Observations where SentinelScale recommended the exact same replicas as HPA.")
    divergence_count: int = Field(..., description="Observations where SentinelScale differed from HPA.")
    agreement_rate: float = Field(..., ge=0.0, le=1.0, description="Proportion of matching decisions.")
    divergence_rate: float = Field(..., ge=0.0, le=1.0, description="Proportion of diverging decisions.")
    average_divergence: float = Field(..., description="Mean signed divergence (negative = suppressed overprovisioning, positive = proactive scale-up).")
    max_absolute_divergence: int = Field(..., description="Maximum absolute difference in replicas.")
    positive_divergence_count: int = Field(default=0, description="Count of observations where SentinelScale recommended more replicas.")
    negative_divergence_count: int = Field(default=0, description="Count of observations where SentinelScale recommended fewer replicas.")
    divergence_distribution: Dict[str, int] = Field(default_factory=dict, description="Distribution of pod deltas (e.g. {'-2': 10, '0': 50, '+3': 2}).")

