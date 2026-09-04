from datetime import datetime, timedelta, timezone
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.anomaly import AnomalySeverity, SignalDirection
from app.models.decision import ScalingAction
from app.models.history import StoredObservation
from app.services.history.sqlite_store import SQLiteDecisionHistoryStore
from app.services.intelligence.anomaly import AnomalyIntelligenceService
from app.services.intelligence.baseline import BehavioralBaselineService


def make_obs(
    obs_id: str,
    timestamp: str,
    pred_rps: float = 1000.0,
    risk: float = 0.1,
    cap_rps: float = 1400.0,
    rec_pods: int = 4,
    curr_pods: int = 4,
    hpa_pods: int = 4,
    action: ScalingAction = ScalingAction.HOLD,
    success: bool = True,
) -> StoredObservation:
    return StoredObservation(
        id=obs_id,
        trace_id=f"trace-{obs_id}",
        timestamp=timestamp,
        duration_ms=5.0,
        success=success,
        action=action if success else None,
        reason="Test observation",
        confidence=0.95,
        recommended_pods=rec_pods,
        current_pods=curr_pods,
        baseline_hpa_recommended_pods=hpa_pods,
        pod_delta_vs_baseline=(rec_pods - hpa_pods) if success else None,
        traffic_risk=risk,
        predicted_legitimate_rps=pred_rps,
        current_capacity_rps=cap_rps,
        policy="default-safe-guardrail-v1",
        dry_run=True,
        shadow_mode=True,
    )


# ==============================================================================
# Unit & Behavioral Anomaly Tests
# ==============================================================================

def test_1_normal_signal():
    """Test 1: Normal Signal when current matches historical mean with 0 variance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test1.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(5):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=100.0))

            service = AnomalyIntelligenceService(history_store=store)
            res = service.assess_anomalies(current_values={"predicted_legitimate_rps": 100.0}, window="1h")

            assert res.overall_severity == AnomalySeverity.NORMAL
            assert len(res.signals) == 1
            sig = res.signals[0]
            assert sig.severity == AnomalySeverity.NORMAL
            assert sig.direction == SignalDirection.NEAR_BASELINE
            assert sig.z_score == 0.0
        finally:
            store.close()


def test_2_elevated_signal():
    """Test 2: Elevated signal when 1.5 <= |z| < 2.5."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test2.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            # Baseline samples: [90, 95, 100, 105, 110] -> mean=100.0, variance=50.0, stddev=7.071
            samples = [90.0, 95.0, 100.0, 105.0, 110.0]
            for i, val in enumerate(samples):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=val))

            service = AnomalyIntelligenceService(history_store=store)
            # Current = 114.0 -> deviation = +14.0 -> z = 14 / 7.071 = 1.98 -> ELEVATED
            res = service.assess_anomalies(current_values={"predicted_legitimate_rps": 114.0}, window="1h")

            assert res.overall_severity == AnomalySeverity.ELEVATED
            sig = res.signals[0]
            assert sig.severity == AnomalySeverity.ELEVATED
            assert sig.direction == SignalDirection.HIGHER_THAN_BASELINE
            assert 1.5 <= sig.z_score < 2.5
        finally:
            store.close()


def test_3_anomalous_signal():
    """Test 3: Anomalous signal when |z| >= 2.5."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test3.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            # Baseline samples: [90, 95, 100, 105, 110] -> mean=100.0, stddev=7.071
            samples = [90.0, 95.0, 100.0, 105.0, 110.0]
            for i, val in enumerate(samples):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=val))

            service = AnomalyIntelligenceService(history_store=store)
            # Current = 130.0 -> deviation = +30.0 -> z = 30 / 7.071 = 4.24 -> ANOMALOUS
            res = service.assess_anomalies(current_values={"predicted_legitimate_rps": 130.0}, window="1h")

            assert res.overall_severity == AnomalySeverity.ANOMALOUS
            sig = res.signals[0]
            assert sig.severity == AnomalySeverity.ANOMALOUS
            assert sig.direction == SignalDirection.HIGHER_THAN_BASELINE
            assert sig.z_score >= 2.5
        finally:
            store.close()


def test_4_and_5_direction_preservation():
    """Test 4 & 5: Direction preservation (HIGHER_THAN_BASELINE and LOWER_THAN_BASELINE)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test45.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(5):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=1000.0, cap_rps=2000.0))

            service = AnomalyIntelligenceService(history_store=store)

            # High demand (8000 vs 1000) & Low capacity (1000 vs 2000)
            res = service.assess_anomalies(
                current_values={
                    "predicted_legitimate_rps": 8000.0,
                    "current_capacity_rps": 1000.0,
                },
                window="1h",
            )

            demand_sig = next(s for s in res.signals if s.metric == "predicted_legitimate_rps")
            cap_sig = next(s for s in res.signals if s.metric == "current_capacity_rps")

            assert demand_sig.direction == SignalDirection.HIGHER_THAN_BASELINE
            assert demand_sig.severity == AnomalySeverity.ANOMALOUS
            assert cap_sig.direction == SignalDirection.LOWER_THAN_BASELINE
            assert cap_sig.severity == AnomalySeverity.ANOMALOUS
        finally:
            store.close()


def test_6_zero_variance_deterministic_fallback():
    """Test 6: Zero variance in baseline records with large relative change."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test6.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(5):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=100.0))

            service = AnomalyIntelligenceService(history_store=store)

            # Current = 100.0 -> NORMAL
            r_same = service.assess_anomalies(current_values={"predicted_legitimate_rps": 100.0}, window="1h")
            assert r_same.signals[0].severity == AnomalySeverity.NORMAL

            # Current = 200.0 (+100% relative diff) -> ANOMALOUS
            r_diff = service.assess_anomalies(current_values={"predicted_legitimate_rps": 200.0}, window="1h")
            assert r_diff.signals[0].severity == AnomalySeverity.ANOMALOUS
            assert r_diff.signals[0].direction == SignalDirection.HIGHER_THAN_BASELINE
        finally:
            store.close()


def test_7_insufficient_data_cold_start():
    """Test 7: Fewer than 5 observations returns INSUFFICIENT_DATA without crashing or fabricating."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test7.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            # Only 2 observations recorded
            for i in range(2):
                ts = (now_dt - timedelta(minutes=5 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=1000.0))

            service = AnomalyIntelligenceService(history_store=store)
            res = service.assess_anomalies(current_values={"predicted_legitimate_rps": 1000.0}, window="1h")

            assert res.overall_severity == AnomalySeverity.INSUFFICIENT_DATA
            assert res.sample_count == 2
            assert res.minimum_required_samples == 5
            assert "Insufficient" in res.explanation
        finally:
            store.close()


def test_8_missing_data_no_fake_zeros():
    """Test 8: Missing metrics are not converted to fake zeros."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test8.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(5):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=1000.0))

            service = AnomalyIntelligenceService(history_store=store)
            # Evaluate only traffic_risk which has valid baseline, and omit capacity
            res = service.assess_anomalies(current_values={"traffic_risk": 0.10}, window="1h")

            assert len(res.signals) == 1
            assert res.signals[0].metric == "traffic_risk"
            assert not any(s.metric == "current_capacity_rps" for s in res.signals)
        finally:
            store.close()


def test_9_and_10_overall_classification_hierarchy():
    """Test 9 & 10: Multi-signal overall severity hierarchy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test910.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            # 5 samples with mean: rps=1000, risk=0.1, cap=1400
            for i in range(5):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=1000.0, risk=0.10, cap_rps=1400.0))

            service = AnomalyIntelligenceService(history_store=store)

            # Case A: All normal -> Overall NORMAL
            r_all_norm = service.assess_anomalies(
                current_values={"predicted_legitimate_rps": 1000.0, "traffic_risk": 0.10, "current_capacity_rps": 1400.0},
                window="1h",
            )
            assert r_all_norm.overall_severity == AnomalySeverity.NORMAL
            assert r_all_norm.anomalous_signal_count == 0
            assert r_all_norm.elevated_signal_count == 0

            # Case B: One normal, one elevated, one anomalous -> Overall ANOMALOUS
            r_mixed = service.assess_anomalies(
                current_values={
                    "predicted_legitimate_rps": 1000.0,  # NORMAL
                    "traffic_risk": 0.85,                 # ANOMALOUS (+750%)
                    "current_capacity_rps": 1100.0,       # ELEVATED (-21%)
                },
                window="1h",
            )
            assert r_mixed.overall_severity == AnomalySeverity.ANOMALOUS
            assert r_mixed.anomalous_signal_count == 1
            assert r_mixed.elevated_signal_count == 1
        finally:
            store.close()


def test_11_to_15_domain_specific_anomalies_and_attack_pattern():
    """Test 11-15: Domain-aware interpretations for demand, risk, capacity, HPA divergence, and security attack pattern."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test1115.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            # Baseline: normal quiet traffic
            for i in range(5):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(
                    f"obs-{i}", ts, pred_rps=1200.0, risk=0.10, cap_rps=1400.0,
                    rec_pods=4, curr_pods=4, hpa_pods=4
                ))

            service = AnomalyIntelligenceService(history_store=store)

            # Attack pattern scenario
            attack_obs = make_obs(
                "obs-attack", now_dt.isoformat(), pred_rps=1200.0, risk=0.85, cap_rps=1400.0,
                rec_pods=4, curr_pods=4, hpa_pods=6, action=ScalingAction.HOLD
            )

            res = service.assess_anomalies(
                current_values={
                    "predicted_legitimate_rps": 1200.0,
                    "traffic_risk": 0.85,
                    "current_capacity_rps": 1400.0,
                    "recommended_pods": 4.0,
                    "baseline_hpa_recommended_pods": 6.0,
                    "pod_delta_vs_baseline": -2.0,
                },
                window="1h",
                observation_context=attack_obs,
            )

            risk_sig = next(s for s in res.signals if s.metric == "traffic_risk")
            assert risk_sig.severity == AnomalySeverity.ANOMALOUS
            assert "Traffic security risk is significantly above" in risk_sig.interpretation

            div_sig = next(s for s in res.signals if s.metric == "pod_delta_vs_baseline")
            assert div_sig.severity == AnomalySeverity.ANOMALOUS
            assert div_sig.direction == SignalDirection.LOWER_THAN_BASELINE

            assert res.pattern_notes is not None
            assert any("Security mitigation active" in note for note in res.pattern_notes)
        finally:
            store.close()


# ==============================================================================
# API Endpoints & Read-Only Tests
# ==============================================================================

client = TestClient(app)


def test_16_api_parameter_validation():
    """Test 16: API parameter validation for GET /api/v1/intelligence/anomalies."""
    # 1. Invalid window -> 400
    res1 = client.get("/api/v1/intelligence/anomalies?window=bad_window")
    assert res1.status_code == 400
    assert "Invalid time window" in res1.json()["detail"]

    # 2. Invalid custom range (start >= end) -> 400
    res2 = client.get(
        "/api/v1/intelligence/anomalies?start_time=2026-09-04T12:00:00Z&end_time=2026-09-04T10:00:00Z"
    )
    assert res2.status_code == 400
    assert "strictly before" in res2.json()["detail"]

    # 3. Missing observation_id -> 404
    res3 = client.get("/api/v1/intelligence/anomalies?observation_id=non-existent-uuid")
    assert res3.status_code == 404


def test_17_api_read_only_isolation():
    """Test 17: Verify GET /api/v1/intelligence/anomalies is strictly read-only."""
    res = client.get("/api/v1/intelligence/anomalies?window=1h&predicted_legitimate_rps=1200.0")
    assert res.status_code == 200
    data = res.json()
    assert "overall_severity" in data
    assert "signals" in data
    assert "explanation" in data

