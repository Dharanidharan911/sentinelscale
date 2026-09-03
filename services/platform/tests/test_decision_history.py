import asyncio
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.decision import ScalingAction, ScalingDecision
from app.models.history import HistoryStats, StoredObservation
from app.services.context_aggregator import AggregationError, ContextAggregatorService
from app.services.history.sqlite_store import SQLiteDecisionHistoryStore
from app.services.observation_scheduler import ObservationSchedulerService


def make_sample_stored_observation(
    obs_id=None,
    trace_id="trace-hist-001",
    timestamp=None,
    success=True,
    action=ScalingAction.HOLD,
    recommended_pods=4,
    error_type=None,
    error_message=None,
):
    obs_id = obs_id or str(uuid.uuid4())
    timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    completed_at = datetime.now(timezone.utc).isoformat()

    return StoredObservation(
        id=obs_id,
        trace_id=trace_id,
        timestamp=timestamp,
        completed_at=completed_at,
        duration_ms=45.2,
        success=success,
        action=action if success else None,
        reason="Test evaluation rationale" if success else None,
        confidence=0.92 if success else None,
        recommended_pods=recommended_pods if success else None,
        current_pods=4 if success else None,
        baseline_hpa_recommended_pods=6 if success else None,
        pod_delta_vs_baseline=-2 if success else None,
        traffic_risk=0.85 if success else None,
        predicted_legitimate_rps=1200.0 if success else None,
        current_capacity_rps=1400.0 if success else None,
        policy="default-safe-guardrail-v1" if success else None,
        dry_run=True,
        shadow_mode=True,
        error_type=error_type,
        error_message=error_message,
        scaling_decision_json='{"action": "HOLD"}' if success else None,
    )


# ==============================================================================
# 1. Store Initialization & Schema Safety Tests
# ==============================================================================

def test_sqlite_store_initialization_and_idempotence():
    """Verify database initialization creates tables and repeated calls are safe."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "subdir", "test_history.db")
        store1 = SQLiteDecisionHistoryStore(db_path=db_path)
        assert os.path.exists(db_path)

        # Idempotent re-initialization
        store2 = SQLiteDecisionHistoryStore(db_path=db_path)
        stats = store2.get_stats()
        assert stats.total_observations == 0

        store1.close()
        store2.close()


# ==============================================================================
# 2. Record & Retrieval Tests
# ==============================================================================

def test_record_and_get_successful_observation():
    """Verify recording a successful observation preserves full fidelity."""
    store = SQLiteDecisionHistoryStore(db_path=":memory:")
    obs = make_sample_stored_observation(
        trace_id="trace-success-999",
        action=ScalingAction.SCALE,
        recommended_pods=8,
    )

    rec_id = store.record_observation(obs)
    assert rec_id == obs.id

    fetched = store.get_observation(obs.id)
    assert fetched is not None
    assert fetched.id == obs.id
    assert fetched.trace_id == "trace-success-999"
    assert fetched.success is True
    assert fetched.action == ScalingAction.SCALE
    assert fetched.recommended_pods == 8
    assert fetched.dry_run is True
    assert fetched.shadow_mode is True
    assert fetched.scaling_decision_json == '{"action": "HOLD"}'


def test_record_and_get_failed_observation():
    """Verify recording an observation failure preserves diagnostics with no fake decision."""
    store = SQLiteDecisionHistoryStore(db_path=":memory:")
    obs = make_sample_stored_observation(
        trace_id="trace-fail-888",
        success=False,
        error_type="UpstreamTrafficIntelligenceError",
        error_message="HTTP 502 received from traffic-intelligence:8001",
    )

    store.record_observation(obs)
    fetched = store.get_observation(obs.id)

    assert fetched is not None
    assert fetched.success is False
    assert fetched.action is None
    assert fetched.recommended_pods is None
    assert fetched.error_type == "UpstreamTrafficIntelligenceError"
    assert "HTTP 502" in fetched.error_message


def test_get_by_trace_id():
    """Verify retrieval of all observations matching a specific trace_id."""
    store = SQLiteDecisionHistoryStore(db_path=":memory:")
    trace = "trace-multi-001"

    obs1 = make_sample_stored_observation(trace_id=trace)
    obs2 = make_sample_stored_observation(trace_id=trace)
    obs3 = make_sample_stored_observation(trace_id="other-trace")

    store.record_observation(obs1)
    store.record_observation(obs2)
    store.record_observation(obs3)

    results = store.get_by_trace_id(trace)
    assert len(results) == 2
    assert all(r.trace_id == trace for r in results)


# ==============================================================================
# 3. Listing, Pagination & Filtering Tests
# ==============================================================================

def test_list_observations_ordering_and_filters():
    """Verify listing newest-first ordering and filters."""
    store = SQLiteDecisionHistoryStore(db_path=":memory:")

    now = datetime.now(timezone.utc)
    t1 = (now - timedelta(minutes=10)).isoformat()
    t2 = (now - timedelta(minutes=5)).isoformat()
    t3 = now.isoformat()

    obs1 = make_sample_stored_observation(timestamp=t1, success=True, action=ScalingAction.HOLD)
    obs2 = make_sample_stored_observation(timestamp=t2, success=True, action=ScalingAction.SCALE)
    obs3 = make_sample_stored_observation(timestamp=t3, success=False, error_type="Timeout")

    store.record_observation(obs1)
    store.record_observation(obs2)
    store.record_observation(obs3)

    # 1. Default listing (newest first)
    all_obs = store.list_observations(limit=10)
    assert len(all_obs) == 3
    assert all_obs[0].id == obs3.id
    assert all_obs[1].id == obs2.id
    assert all_obs[2].id == obs1.id

    # 2. Filter by success=True
    successful = store.list_observations(success=True)
    assert len(successful) == 2
    assert all(r.success is True for r in successful)

    # 3. Filter by action="SCALE"
    scaled = store.list_observations(action="SCALE")
    assert len(scaled) == 1
    assert scaled[0].id == obs2.id

    # 4. Limit and offset
    page1 = store.list_observations(limit=1, offset=0)
    assert len(page1) == 1
    assert page1[0].id == obs3.id

    page2 = store.list_observations(limit=1, offset=1)
    assert len(page2) == 1
    assert page2[0].id == obs2.id


# ==============================================================================
# 4. Retention Cleanup Tests
# ==============================================================================

def test_cleanup_old_observations():
    """Verify observations older than retention period are deleted."""
    store = SQLiteDecisionHistoryStore(db_path=":memory:")

    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=10)).isoformat()
    recent_ts = (now - timedelta(days=2)).isoformat()

    old_obs = make_sample_stored_observation(timestamp=old_ts)
    recent_obs = make_sample_stored_observation(timestamp=recent_ts)

    store.record_observation(old_obs)
    store.record_observation(recent_obs)

    assert store.get_stats().total_observations == 2

    # Cleanup with 7-day retention
    deleted = store.cleanup_old_observations(retention_days=7)
    assert deleted == 1

    remaining = store.list_observations()
    assert len(remaining) == 1
    assert remaining[0].id == recent_obs.id


# ==============================================================================
# 5. Observation Scheduler Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_scheduler_records_successful_observation_in_history():
    """Verify ObservationScheduler automatically records successful cycles."""
    store = SQLiteDecisionHistoryStore(db_path=":memory:")
    mock_aggregator = MagicMock(spec=ContextAggregatorService)

    decision = ScalingDecision(
        decision_id="dec-sched-01",
        event_id="evt-sched-01",
        trace_id="trace-sched-test",
        timestamp="2026-09-03T18:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="policy-rules-v0",
        action=ScalingAction.HOLD,
        reason="Scheduler test",
        confidence=0.95,
        traffic_risk=0.85,
        predicted_legitimate_rps=1200.0,
        current_capacity_rps=1400.0,
        current_pods=4,
        recommended_pods=4,
        baseline_hpa_recommended_pods=4,
        pod_delta_vs_baseline=0,
        policy="default-safe-guardrail-v1",
        dry_run=True,
        shadow_mode=True,
    )
    mock_aggregator.orchestrate_decision = AsyncMock(return_value=decision)

    scheduler = ObservationSchedulerService(
        aggregator=mock_aggregator,
        history_store=store,
        interval_seconds=1.0,
    )

    res = await scheduler.execute_evaluation(trace_id="trace-sched-test")
    assert res is not None
    assert res.success is True

    # Verify history record
    records = store.get_by_trace_id("trace-sched-test")
    assert len(records) == 1
    rec = records[0]
    assert rec.trace_id == "trace-sched-test"
    assert rec.action == ScalingAction.HOLD
    assert rec.recommended_pods == 4
    assert rec.dry_run is True


@pytest.mark.asyncio
async def test_scheduler_records_failed_observation_in_history():
    """Verify ObservationScheduler automatically records failure cycles."""
    store = SQLiteDecisionHistoryStore(db_path=":memory:")
    mock_aggregator = MagicMock(spec=ContextAggregatorService)
    mock_aggregator.orchestrate_decision = AsyncMock(
        side_effect=AggregationError("Traffic Intelligence", "502 Bad Gateway")
    )

    scheduler = ObservationSchedulerService(
        aggregator=mock_aggregator,
        history_store=store,
    )

    res = await scheduler.execute_evaluation(trace_id="trace-sched-fail")
    assert res is not None
    assert res.success is False

    records = store.get_by_trace_id("trace-sched-fail")
    assert len(records) == 1
    rec = records[0]
    assert rec.success is False
    assert "[Traffic Intelligence] 502 Bad Gateway" in rec.error_message


@pytest.mark.asyncio
async def test_history_persistence_failure_does_not_crash_scheduler():
    """Verify that if the history store raises an exception, the scheduler still succeeds."""
    mock_store = MagicMock(spec=SQLiteDecisionHistoryStore)
    mock_store.record_observation.side_effect = RuntimeError("Database disk full")

    mock_aggregator = MagicMock(spec=ContextAggregatorService)
    decision = ScalingDecision(
        decision_id="dec-sched-01",
        event_id="evt-sched-01",
        trace_id="trace-db-err",
        timestamp="2026-09-03T18:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="policy-rules-v0",
        action=ScalingAction.HOLD,
        reason="Scheduler test",
        confidence=0.95,
        traffic_risk=0.85,
        predicted_legitimate_rps=1200.0,
        current_capacity_rps=1400.0,
        current_pods=4,
        recommended_pods=4,
        baseline_hpa_recommended_pods=4,
        pod_delta_vs_baseline=0,
        policy="default-safe-guardrail-v1",
        dry_run=True,
        shadow_mode=True,
    )
    mock_aggregator.orchestrate_decision = AsyncMock(return_value=decision)

    scheduler = ObservationSchedulerService(
        aggregator=mock_aggregator,
        history_store=mock_store,
    )

    res = await scheduler.execute_evaluation(trace_id="trace-db-err")
    assert res is not None
    assert res.success is True  # Scheduler evaluation still succeeded!
    assert scheduler.evaluation_count == 1


# ==============================================================================
# 6. Read-Only History API Tests
# ==============================================================================

client = TestClient(app)


def test_api_history_endpoints():
    """Test GET /api/v1/history, GET /api/v1/history/stats, and GET /api/v1/history/{id}."""
    # 1. Fetch stats
    stats_res = client.get("/api/v1/history/stats")
    assert stats_res.status_code == 200
    assert "total_observations" in stats_res.json()

    # 2. Fetch history list
    list_res = client.get("/api/v1/history?limit=10")
    assert list_res.status_code == 200
    assert isinstance(list_res.json(), list)

    # 3. Fetch non-existent ID -> 404
    missing_res = client.get("/api/v1/history/non-existent-uuid")
    assert missing_res.status_code == 404

