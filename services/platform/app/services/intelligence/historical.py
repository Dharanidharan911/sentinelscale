from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from app.logging import logger
from app.models.decision import ScalingAction
from app.models.history import StoredObservation
from app.models.intelligence import (
    CapacityHistoricalStats,
    DecisionDistributionStats,
    DecisionQualityStats,
    DemandHistoricalStats,
    HistoricalDivergence,
    HistoricalSummary,
    HistoricalTrends,
    HpaComparisonStats,
    ObservationCountStats,
    PodRecommendationStats,
    TimeRangeInfo,
    TrafficRiskHistoricalStats,
    TrendBucket,
)
from app.services.history.base import DecisionHistoryStore
from app.services.intelligence.base import HistoricalIntelligenceService

SUPPORTED_WINDOWS: Dict[str, int] = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "6h": 6 * 60 * 60,
    "24h": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60,
}


def parse_and_validate_time_window(
    window: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> Tuple[datetime, datetime, Optional[str]]:
    """
    Resolve and validate time window parameters.
    Returns (start_dt, end_dt, window_name).
    Raises ValueError on malformed or invalid inputs.
    """
    if window is not None:
        norm_window = window.strip().lower()
        if norm_window not in SUPPORTED_WINDOWS:
            supported = ", ".join(SUPPORTED_WINDOWS.keys())
            raise ValueError(f"Invalid time window '{window}'. Supported windows: {supported}")
        duration_sec = SUPPORTED_WINDOWS[norm_window]
        now_dt = datetime.now(timezone.utc)
        start_dt = now_dt - timedelta(seconds=duration_sec)
        return start_dt, now_dt, norm_window

    if start_time is not None or end_time is not None:
        if start_time is None or end_time is None:
            raise ValueError("Both start_time and end_time must be provided for custom time ranges.")

        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except Exception as e:
            raise ValueError(f"Invalid start_time ISO-8601 timestamp: '{start_time}'") from e

        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except Exception as e:
            raise ValueError(f"Invalid end_time ISO-8601 timestamp: '{end_time}'") from e

        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        if start_dt >= end_dt:
            raise ValueError(f"start_time ({start_time}) must be strictly before end_time ({end_time}).")

        return start_dt, end_dt, None

    # Default fallback: 1 hour window
    now_dt = datetime.now(timezone.utc)
    start_dt = now_dt - timedelta(seconds=3600)
    return start_dt, now_dt, "1h"


def select_default_bucket_seconds(total_seconds: float) -> int:
    """Select appropriate trend bucket interval based on window duration."""
    if total_seconds <= 15 * 60:
        return 60  # 1-minute buckets
    elif total_seconds <= 60 * 60:
        return 5 * 60  # 5-minute buckets
    elif total_seconds <= 6 * 60 * 60:
        return 15 * 60  # 15-minute buckets
    elif total_seconds <= 24 * 60 * 60:
        return 60 * 60  # 1-hour buckets
    else:
        return 6 * 60 * 60  # 6-hour buckets


class DefaultHistoricalIntelligenceService(HistoricalIntelligenceService):
    """
    Production deterministic Historical Intelligence service.
    Directly queries the durable DecisionHistoryStore and calculates statistical summaries,
    time-series trend buckets, and baseline HPA divergence analysis.
    """

    def __init__(self, history_store: DecisionHistoryStore):
        self._history_store = history_store

    def _fetch_records(self, start_dt: datetime, end_dt: datetime) -> List[StoredObservation]:
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()
        return self._history_store.get_observations_in_range(start_time=start_iso, end_time=end_iso)

    def get_summary(
        self,
        window: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> HistoricalSummary:
        start_dt, end_dt, window_name = parse_and_validate_time_window(window, start_time, end_time)
        observations = self._fetch_records(start_dt, end_dt)

        time_range = TimeRangeInfo(
            start_time=start_dt.isoformat(),
            end_time=end_dt.isoformat(),
            window=window_name,
        )

        total_obs = len(observations)
        if total_obs == 0:
            return HistoricalSummary(
                time_range=time_range,
                observation_counts=ObservationCountStats(
                    total_observations=0,
                    successful_observations=0,
                    failed_observations=0,
                    success_rate=0.0,
                ),
                decision_distribution=DecisionDistributionStats(
                    scale_events=0,
                    hold_events=0,
                    rate_limit_events=0,
                    scale_down_events=0,
                    hold_under_high_risk_events=0,
                    legitimate_demand_scale_events=0,
                ),
                demand_stats=DemandHistoricalStats(),
                traffic_risk_stats=TrafficRiskHistoricalStats(),
                capacity_stats=CapacityHistoricalStats(),
                pod_stats=PodRecommendationStats(),
                hpa_comparison=HpaComparisonStats(
                    hpa_scale_events=0,
                    sentinelscale_scale_events=0,
                    comparable_observations=0,
                    agreement_count=0,
                    divergence_count=0,
                    agreement_rate=0.0,
                    divergence_rate=0.0,
                    average_hpa_divergence=0.0,
                    max_hpa_divergence=0,
                    positive_divergence_count=0,
                    negative_divergence_count=0,
                ),
                decision_quality=DecisionQualityStats(
                    decision_success_rate=0.0,
                    decision_failure_rate=0.0,
                    sentinelscale_vs_hpa_agreement_rate=0.0,
                    sentinelscale_vs_hpa_divergence_rate=0.0,
                    hold_under_high_risk_frequency=0.0,
                    legitimate_demand_scale_frequency=0.0,
                    scale_down_frequency=0.0,
                    upstream_failure_frequency={},
                ),
            )

        successful_records = [o for o in observations if o.success]
        failed_records = [o for o in observations if not o.success]
        success_count = len(successful_records)
        failed_count = len(failed_records)
        success_rate = round(success_count / total_obs, 4)
        failure_rate = round(failed_count / total_obs, 4)

        # Decision distribution
        scale_events = sum(1 for o in successful_records if o.action == ScalingAction.SCALE)
        hold_events = sum(1 for o in successful_records if o.action == ScalingAction.HOLD)
        rate_limit_events = sum(1 for o in successful_records if o.action == ScalingAction.RATE_LIMIT)

        scale_down_events = sum(
            1 for o in successful_records
            if o.recommended_pods is not None and o.current_pods is not None and o.recommended_pods < o.current_pods
        )

        hold_under_high_risk_events = sum(
            1 for o in successful_records
            if o.action == ScalingAction.HOLD and o.traffic_risk is not None and o.traffic_risk >= 0.70
        )

        legitimate_demand_scale_events = sum(
            1 for o in successful_records
            if o.action == ScalingAction.SCALE
            and o.recommended_pods is not None
            and o.current_pods is not None
            and o.recommended_pods > o.current_pods
            and (o.traffic_risk is None or o.traffic_risk < 0.70)
        )

        # Demand stats
        pred_rps_list = [o.predicted_legitimate_rps for o in successful_records if o.predicted_legitimate_rps is not None]
        avg_pred_rps = round(sum(pred_rps_list) / len(pred_rps_list), 2) if pred_rps_list else None
        peak_pred_rps = round(max(pred_rps_list), 2) if pred_rps_list else None
        min_pred_rps = round(min(pred_rps_list), 2) if pred_rps_list else None

        # Traffic risk stats
        risk_list = [o.traffic_risk for o in successful_records if o.traffic_risk is not None]
        avg_risk = round(sum(risk_list) / len(risk_list), 4) if risk_list else None
        peak_risk = round(max(risk_list), 4) if risk_list else None
        high_risk_count = sum(1 for r in risk_list if r >= 0.70)

        # Capacity stats
        cap_list = [o.current_capacity_rps for o in successful_records if o.current_capacity_rps is not None]
        avg_capacity = round(sum(cap_list) / len(cap_list), 2) if cap_list else None

        # Pod recommendation stats
        rec_pods_list = [o.recommended_pods for o in successful_records if o.recommended_pods is not None]
        curr_pods_list = [o.current_pods for o in successful_records if o.current_pods is not None]
        avg_rec_pods = round(sum(rec_pods_list) / len(rec_pods_list), 2) if rec_pods_list else None
        avg_curr_pods = round(sum(curr_pods_list) / len(curr_pods_list), 2) if curr_pods_list else None
        max_rec_pods = max(rec_pods_list) if rec_pods_list else None
        min_rec_pods = min(rec_pods_list) if rec_pods_list else None

        # HPA comparison
        hpa_comparable = [
            o for o in successful_records
            if o.recommended_pods is not None and o.baseline_hpa_recommended_pods is not None
        ]
        comp_count = len(hpa_comparable)
        agreement_count = sum(1 for o in hpa_comparable if o.recommended_pods == o.baseline_hpa_recommended_pods)
        divergence_count = sum(1 for o in hpa_comparable if o.recommended_pods != o.baseline_hpa_recommended_pods)
        agreement_rate = round(agreement_count / comp_count, 4) if comp_count > 0 else 0.0
        divergence_rate = round(divergence_count / comp_count, 4) if comp_count > 0 else 0.0

        deltas = [
            o.pod_delta_vs_baseline if o.pod_delta_vs_baseline is not None
            else (o.recommended_pods - o.baseline_hpa_recommended_pods)
            for o in hpa_comparable
        ]
        avg_divergence = round(sum(deltas) / len(deltas), 2) if deltas else 0.0
        max_divergence = max([abs(d) for d in deltas]) if deltas else 0
        pos_divergence = sum(1 for d in deltas if d > 0)
        neg_divergence = sum(1 for d in deltas if d < 0)

        hpa_scale_events = sum(
            1 for o in hpa_comparable
            if o.current_pods is not None and o.baseline_hpa_recommended_pods > o.current_pods
        )
        sentinelscale_scale_events = sum(
            1 for o in hpa_comparable
            if o.current_pods is not None and o.recommended_pods > o.current_pods
        )

        # Failure distribution
        upstream_failures: Dict[str, int] = {}
        for o in failed_records:
            etype = o.error_type or "unknown"
            upstream_failures[etype] = upstream_failures.get(etype, 0) + 1

        # Decision quality rates
        hold_under_risk_freq = round(hold_under_high_risk_events / success_count, 4) if success_count > 0 else 0.0
        legit_scale_freq = round(legitimate_demand_scale_events / success_count, 4) if success_count > 0 else 0.0
        scale_down_freq = round(scale_down_events / success_count, 4) if success_count > 0 else 0.0

        return HistoricalSummary(
            time_range=time_range,
            observation_counts=ObservationCountStats(
                total_observations=total_obs,
                successful_observations=success_count,
                failed_observations=failed_count,
                success_rate=success_rate,
            ),
            decision_distribution=DecisionDistributionStats(
                scale_events=scale_events,
                hold_events=hold_events,
                rate_limit_events=rate_limit_events,
                scale_down_events=scale_down_events,
                hold_under_high_risk_events=hold_under_high_risk_events,
                legitimate_demand_scale_events=legitimate_demand_scale_events,
            ),
            demand_stats=DemandHistoricalStats(
                average_predicted_legitimate_rps=avg_pred_rps,
                peak_predicted_legitimate_rps=peak_pred_rps,
                min_predicted_legitimate_rps=min_pred_rps,
            ),
            traffic_risk_stats=TrafficRiskHistoricalStats(
                average_traffic_risk=avg_risk,
                peak_traffic_risk=peak_risk,
                high_risk_observations=high_risk_count,
            ),
            capacity_stats=CapacityHistoricalStats(
                average_current_capacity_rps=avg_capacity,
            ),
            pod_stats=PodRecommendationStats(
                average_recommended_pods=avg_rec_pods,
                average_current_pods=avg_curr_pods,
                max_recommended_pods=max_rec_pods,
                min_recommended_pods=min_rec_pods,
            ),
            hpa_comparison=HpaComparisonStats(
                hpa_scale_events=hpa_scale_events,
                sentinelscale_scale_events=sentinelscale_scale_events,
                comparable_observations=comp_count,
                agreement_count=agreement_count,
                divergence_count=divergence_count,
                agreement_rate=agreement_rate,
                divergence_rate=divergence_rate,
                average_hpa_divergence=avg_divergence,
                max_hpa_divergence=max_divergence,
                positive_divergence_count=pos_divergence,
                negative_divergence_count=neg_divergence,
            ),
            decision_quality=DecisionQualityStats(
                decision_success_rate=success_rate,
                decision_failure_rate=failure_rate,
                sentinelscale_vs_hpa_agreement_rate=agreement_rate,
                sentinelscale_vs_hpa_divergence_rate=divergence_rate,
                hold_under_high_risk_frequency=hold_under_risk_freq,
                legitimate_demand_scale_frequency=legit_scale_freq,
                scale_down_frequency=scale_down_freq,
                upstream_failure_frequency=upstream_failures,
            ),
        )

    def get_trends(
        self,
        window: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        bucket_seconds: Optional[int] = None,
    ) -> HistoricalTrends:
        start_dt, end_dt, window_name = parse_and_validate_time_window(window, start_time, end_time)
        total_duration = (end_dt - start_dt).total_seconds()

        if bucket_seconds is not None:
            if bucket_seconds <= 0:
                raise ValueError("bucket_seconds must be strictly positive.")
            step_sec = bucket_seconds
        else:
            step_sec = select_default_bucket_seconds(total_duration)

        observations = self._fetch_records(start_dt, end_dt)

        # Parse observation timestamps for fast bucketing
        parsed_obs: List[Tuple[datetime, StoredObservation]] = []
        for o in observations:
            try:
                obs_dt = datetime.fromisoformat(o.timestamp.replace("Z", "+00:00"))
                if obs_dt.tzinfo is None:
                    obs_dt = obs_dt.replace(tzinfo=timezone.utc)
                parsed_obs.append((obs_dt, o))
            except Exception:
                continue

        buckets: List[TrendBucket] = []
        cur_start = start_dt
        while cur_start < end_dt:
            cur_end = min(cur_start + timedelta(seconds=step_sec), end_dt)

            # Match records in bucket [cur_start, cur_end) except the last bucket which is [cur_start, cur_end]
            if cur_end == end_dt:
                bucket_records = [o for dt, o in parsed_obs if cur_start <= dt <= cur_end]
            else:
                bucket_records = [o for dt, o in parsed_obs if cur_start <= dt < cur_end]

            total_b = len(bucket_records)
            successful_b = [o for o in bucket_records if o.success]
            failed_b = [o for o in bucket_records if not o.success]

            # Averages over successful records
            pred_rps_b = [o.predicted_legitimate_rps for o in successful_b if o.predicted_legitimate_rps is not None]
            risk_b = [o.traffic_risk for o in successful_b if o.traffic_risk is not None]
            cap_b = [o.current_capacity_rps for o in successful_b if o.current_capacity_rps is not None]
            rec_pods_b = [o.recommended_pods for o in successful_b if o.recommended_pods is not None]
            hpa_pods_b = [o.baseline_hpa_recommended_pods for o in successful_b if o.baseline_hpa_recommended_pods is not None]

            deltas_b = [
                o.pod_delta_vs_baseline if o.pod_delta_vs_baseline is not None
                else (o.recommended_pods - o.baseline_hpa_recommended_pods)
                for o in successful_b
                if o.recommended_pods is not None and o.baseline_hpa_recommended_pods is not None
            ]

            scale_b = sum(1 for o in successful_b if o.action == ScalingAction.SCALE)
            hold_b = sum(1 for o in successful_b if o.action == ScalingAction.HOLD)
            rate_limit_b = sum(1 for o in successful_b if o.action == ScalingAction.RATE_LIMIT)

            buckets.append(
                TrendBucket(
                    bucket_start=cur_start.isoformat(),
                    bucket_end=cur_end.isoformat(),
                    total_observations=total_b,
                    successful_observations=len(successful_b),
                    failed_observations=len(failed_b),
                    average_predicted_legitimate_rps=round(sum(pred_rps_b) / len(pred_rps_b), 2) if pred_rps_b else None,
                    average_traffic_risk=round(sum(risk_b) / len(risk_b), 4) if risk_b else None,
                    average_current_capacity_rps=round(sum(cap_b) / len(cap_b), 2) if cap_b else None,
                    average_recommended_pods=round(sum(rec_pods_b) / len(rec_pods_b), 2) if rec_pods_b else None,
                    average_baseline_hpa_pods=round(sum(hpa_pods_b) / len(hpa_pods_b), 2) if hpa_pods_b else None,
                    average_divergence=round(sum(deltas_b) / len(deltas_b), 2) if deltas_b else None,
                    scale_count=scale_b,
                    hold_count=hold_b,
                    rate_limit_count=rate_limit_b,
                )
            )

            cur_start = cur_end

        return HistoricalTrends(
            time_range=TimeRangeInfo(
                start_time=start_dt.isoformat(),
                end_time=end_dt.isoformat(),
                window=window_name,
            ),
            bucket_interval_seconds=step_sec,
            total_buckets=len(buckets),
            buckets=buckets,
        )

    def get_divergence(
        self,
        window: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> HistoricalDivergence:
        start_dt, end_dt, window_name = parse_and_validate_time_window(window, start_time, end_time)
        observations = self._fetch_records(start_dt, end_dt)

        time_range = TimeRangeInfo(
            start_time=start_dt.isoformat(),
            end_time=end_dt.isoformat(),
            window=window_name,
        )

        hpa_comparable = [
            o for o in observations
            if o.success and o.recommended_pods is not None and o.baseline_hpa_recommended_pods is not None
        ]

        comp_count = len(hpa_comparable)
        if comp_count == 0:
            return HistoricalDivergence(
                time_range=time_range,
                comparable_observations=0,
                agreement_count=0,
                divergence_count=0,
                agreement_rate=0.0,
                divergence_rate=0.0,
                average_divergence=0.0,
                max_absolute_divergence=0,
                positive_divergence_count=0,
                negative_divergence_count=0,
                divergence_distribution={},
            )

        agreement_count = sum(1 for o in hpa_comparable if o.recommended_pods == o.baseline_hpa_recommended_pods)
        divergence_count = sum(1 for o in hpa_comparable if o.recommended_pods != o.baseline_hpa_recommended_pods)
        agreement_rate = round(agreement_count / comp_count, 4)
        divergence_rate = round(divergence_count / comp_count, 4)

        deltas = [
            o.pod_delta_vs_baseline if o.pod_delta_vs_baseline is not None
            else (o.recommended_pods - o.baseline_hpa_recommended_pods)
            for o in hpa_comparable
        ]

        avg_divergence = round(sum(deltas) / len(deltas), 2)
        max_abs_divergence = max([abs(d) for d in deltas])
        pos_divergence = sum(1 for d in deltas if d > 0)
        neg_divergence = sum(1 for d in deltas if d < 0)

        # Build delta distribution
        dist: Dict[str, int] = {}
        for d in sorted(deltas):
            key = f"+{d}" if d > 0 else str(d)
            dist[key] = dist.get(key, 0) + 1

        return HistoricalDivergence(
            time_range=time_range,
            comparable_observations=comp_count,
            agreement_count=agreement_count,
            divergence_count=divergence_count,
            agreement_rate=agreement_rate,
            divergence_rate=divergence_rate,
            average_divergence=avg_divergence,
            max_absolute_divergence=max_abs_divergence,
            positive_divergence_count=pos_divergence,
            negative_divergence_count=neg_divergence,
            divergence_distribution=dist,
        )

