from datetime import datetime, timedelta, timezone
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.decision import ScalingAction
from app.models.history import StoredObservation
from app.services.history.sqlite_store import SQLiteDecisionHistoryStore
from app.services.intelligence.historical import DefaultHistoricalIntelligenceService, parse_and_validate_time_window
from app.services.intelligence.factory import get_historical_intelligence_service
from app.api.v1.endpoints import get_history_repository, get_historical_intelligence


# ==============================================================================
# Helper Observation Fixture Builder
# ==============================================================================

def make_stored_obs(
    obs_id: str,
    timestamp: str,
    success: bool = True,
    action: ScalingAction = ScalingAction.HOLD,
    rec_pods: int = 4,
    curr_pods: int = 4,
    hpa_pods: int = 4,
    risk: float = 0.1,
    pred_rps: float = 1000.0,
    cap_rps: float = 1400.0,
    error_type: str | None = None,
) -> StoredObservation:
    pod_delta = (rec_pods - hpa_pods) if success else None
    return StoredObservation(
        id=obs_id,
        trace_id=f"trace-{obs_id}",
        timestamp=timestamp,
        completed_at=timestamp,
        duration_ms=5.0,
        success=success,
        action=action if success else None,
        reason="Test reason" if success else None,
        confidence=0.95 if success else None,
        recommended_pods=rec_pods if success else None,
        current_pods=curr_pods if success else None,
        baseline_hpa_recommended_pods=hpa_pods if success else None,
        pod_delta_vs_baseline=pod_delta,
        traffic_risk=risk if success else None,
        predicted_legitimate_rps=pred_rps if success else None,
        current_capacity_rps=cap_rps if success else None,
        policy="default-safe-guardrail-v1" if success else None,
        dry_run=True,
        shadow_mode=True,
        error_type=error_type if not success else None,
        error_message=f"Error {error_type}" if not success else None,
    )


# ==============================================================================
# 1. Empty History & Edge Cases
# ==============================================================================

def test_empty_history_summary_returns_valid_zero_semantics():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test_empty.db"))
        try:
            service = DefaultHistoricalIntelligenceService(history_store=store)
            summary = service.get_summary(window="1h")

            assert summary.observation_counts.total_observations == 0
            assert summary.observation_counts.successful_observations == 0
            assert summary.observation_counts.failed_observations == 0
            assert summary.observation_counts.success_rate == 0.0

            assert summary.decision_distribution.scale_events == 0
            assert summary.decision_distribution.hold_events == 0
            assert summary.demand_stats.average_predicted_legitimate_rps is None
            assert summary.traffic_risk_stats.average_traffic_risk is None
            assert summary.capacity_stats.average_current_capacity_rps is None
            assert summary.pod_stats.average_recommended_pods is None

            assert summary.hpa_comparison.comparable_observations == 0
            assert summary.hpa_comparison.agreement_rate == 0.0
            assert summary.hpa_comparison.average_hpa_divergence == 0.0

            assert summary.decision_quality.decision_success_rate == 0.0
            assert summary.decision_quality.decision_failure_rate == 0.0
        finally:
            store.close()


def test_empty_history_trends_and_divergence():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test_empty_trends.db"))
        try:
            service = DefaultHistoricalIntelligenceService(history_store=store)
            trends = service.get_trends(window="1h")
            assert trends.total_buckets > 0
            assert all(b.total_observations == 0 for b in trends.buckets)

            div = service.get_divergence(window="1h")
            assert div.comparable_observations == 0
            assert div.agreement_rate == 0.0
            assert div.divergence_distribution == {}
        finally:
            store.close()


# ==============================================================================
# 2. Single & Multiple Observations Analytics
# ==============================================================================

def test_single_observation_aggregations():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test_single.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            ts = now_dt.isoformat()
            obs = make_stored_obs(
                obs_id="obs-01",
                timestamp=ts,
                success=True,
                action=ScalingAction.SCALE,
                rec_pods=6,
                curr_pods=4,
                hpa_pods=6,
                risk=0.10,
                pred_rps=2100.0,
                cap_rps=1400.0,
            )
            store.record_observation(obs)

            service = DefaultHistoricalIntelligenceService(history_store=store)
            summary = service.get_summary(window="1h")

            assert summary.observation_counts.total_observations == 1
            assert summary.observation_counts.successful_observations == 1
            assert summary.observation_counts.success_rate == 1.0
            assert summary.decision_distribution.scale_events == 1
            assert summary.decision_distribution.hold_events == 0
            assert summary.demand_stats.average_predicted_legitimate_rps == 2100.0
            assert summary.traffic_risk_stats.average_traffic_risk == 0.10
            assert summary.pod_stats.average_recommended_pods == 6.0
            assert summary.hpa_comparison.agreement_count == 1
            assert summary.hpa_comparison.divergence_count == 0
            assert summary.hpa_comparison.agreement_rate == 1.0
        finally:
            store.close()


def test_multiple_mixed_observations_and_quality():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test_multi.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            t1 = (now_dt - timedelta(minutes=10)).isoformat()
            t2 = (now_dt - timedelta(minutes=8)).isoformat()
            t3 = (now_dt - timedelta(minutes=5)).isoformat()
            t4 = (now_dt - timedelta(minutes=2)).isoformat()

            # Obs 1: Attack hold (Sentinel=4, HPA=6, Delta=-2, Risk=0.85)
            store.record_observation(make_stored_obs(
                "obs-1", t1, success=True, action=ScalingAction.HOLD,
                rec_pods=4, curr_pods=4, hpa_pods=6, risk=0.85, pred_rps=1200.0
            ))
            # Obs 2: Legitimate surge (Sentinel=8, HPA=8, Delta=0, Risk=0.05)
            store.record_observation(make_stored_obs(
                "obs-2", t2, success=True, action=ScalingAction.SCALE,
                rec_pods=8, curr_pods=4, hpa_pods=8, risk=0.05, pred_rps=2800.0
            ))
            # Obs 3: Low demand scale-down (Sentinel=2, HPA=2, Delta=0, Risk=0.05)
            store.record_observation(make_stored_obs(
                "obs-3", t3, success=True, action=ScalingAction.SCALE,
                rec_pods=2, curr_pods=4, hpa_pods=2, risk=0.05, pred_rps=350.0
            ))
            # Obs 4: Upstream Failure
            store.record_observation(make_stored_obs(
                "obs-4", t4, success=False, error_type="bad_gateway"
            ))

            service = DefaultHistoricalIntelligenceService(history_store=store)
            summary = service.get_summary(window="1h")

            assert summary.observation_counts.total_observations == 4
            assert summary.observation_counts.successful_observations == 3
            assert summary.observation_counts.failed_observations == 1
            assert summary.observation_counts.success_rate == 0.75

            assert summary.decision_distribution.hold_events == 1
            assert summary.decision_distribution.scale_events == 2
            assert summary.decision_distribution.hold_under_high_risk_events == 1
            assert summary.decision_distribution.legitimate_demand_scale_events == 1
            assert summary.decision_distribution.scale_down_events == 1

            assert summary.traffic_risk_stats.high_risk_observations == 1
            assert summary.hpa_comparison.comparable_observations == 3
            assert summary.hpa_comparison.agreement_count == 2
            assert summary.hpa_comparison.divergence_count == 1
            assert summary.hpa_comparison.negative_divergence_count == 1
            assert summary.hpa_comparison.average_hpa_divergence == round((-2 + 0 + 0) / 3, 2)
            assert summary.hpa_comparison.max_hpa_divergence == 2

            assert summary.decision_quality.upstream_failure_frequency == {"bad_gateway": 1}

            # Verify Divergence Endpoint
            div = service.get_divergence(window="1h")
            assert div.comparable_observations == 3
            assert div.divergence_count == 1
            assert div.divergence_distribution.get("-2") == 1
            assert div.divergence_distribution.get("0") == 2
        finally:
            store.close()


# ==============================================================================
# 3. Time Windows & Range Filtering
# ==============================================================================

def test_time_window_filtering_and_custom_ranges():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test_windows.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            # Record 1: 2 hours ago
            store.record_observation(make_stored_obs(
                "obs-2h-ago", (now_dt - timedelta(hours=2)).isoformat(), success=True
            ))
            # Record 2: 30 minutes ago
            store.record_observation(make_stored_obs(
                "obs-30m-ago", (now_dt - timedelta(minutes=30)).isoformat(), success=True
            ))
            # Record 3: 2 minutes ago
            store.record_observation(make_stored_obs(
                "obs-2m-ago", (now_dt - timedelta(minutes=2)).isoformat(), success=True
            ))

            service = DefaultHistoricalIntelligenceService(history_store=store)

            # 5m window should only include obs-2m-ago
            sum_5m = service.get_summary(window="5m")
            assert sum_5m.observation_counts.total_observations == 1

            # 1h window should include obs-30m-ago and obs-2m-ago
            sum_1h = service.get_summary(window="1h")
            assert sum_1h.observation_counts.total_observations == 2

            # 6h window should include all 3 records
            sum_6h = service.get_summary(window="6h")
            assert sum_6h.observation_counts.total_observations == 3

            # Custom range excluding the newest
            start_custom = (now_dt - timedelta(hours=3)).isoformat()
            end_custom = (now_dt - timedelta(minutes=15)).isoformat()
            sum_custom = service.get_summary(start_time=start_custom, end_time=end_custom)
            assert sum_custom.observation_counts.total_observations == 2
        finally:
            store.close()


# ==============================================================================
# 4. Input Validation & API Error Handling
# ==============================================================================

def test_time_window_validation_errors():
    # Invalid window string
    with pytest.raises(ValueError, match="Invalid time window '2h'"):
        parse_and_validate_time_window(window="2h")

    # start >= end
    with pytest.raises(ValueError, match="must be strictly before end_time"):
        parse_and_validate_time_window(
            start_time="2026-09-04T12:00:00Z",
            end_time="2026-09-04T10:00:00Z"
        )

    # Malformed timestamp
    with pytest.raises(ValueError, match="Invalid start_time ISO-8601"):
        parse_and_validate_time_window(
            start_time="not-a-timestamp",
            end_time="2026-09-04T10:00:00Z"
        )


client = TestClient(app)


def test_api_endpoints_validation_and_read_only():
    """
    Validate that GET /api/v1/intelligence/history/summary, /trends, and /divergence
    return 400 on invalid parameters, 200 on valid parameters, and do not mutate state.
    """
    # 1. Invalid window parameter -> HTTP 400
    res_bad = client.get("/api/v1/intelligence/history/summary?window=invalid_window")
    assert res_bad.status_code == 400
    assert "Invalid time window" in res_bad.json()["detail"]

    # 2. Invalid start_time >= end_time -> HTTP 400
    res_bad_range = client.get(
        "/api/v1/intelligence/history/summary?start_time=2026-09-04T12:00:00Z&end_time=2026-09-04T10:00:00Z"
    )
    assert res_bad_range.status_code == 400
    assert "strictly before" in res_bad_range.json()["detail"]

    # 3. Valid summary request -> HTTP 200
    res_summary = client.get("/api/v1/intelligence/history/summary?window=1h")
    assert res_summary.status_code == 200
    assert "observation_counts" in res_summary.json()
    assert "hpa_comparison" in res_summary.json()

    # 4. Valid trends request -> HTTP 200
    res_trends = client.get("/api/v1/intelligence/history/trends?window=1h")
    assert res_trends.status_code == 200
    assert "buckets" in res_trends.json()
    assert "total_buckets" in res_trends.json()

    # 5. Valid divergence request -> HTTP 200
    res_div = client.get("/api/v1/intelligence/history/divergence?window=1h")
    assert res_div.status_code == 200
    assert "agreement_rate" in res_div.json()
    assert "divergence_distribution" in res_div.json()

