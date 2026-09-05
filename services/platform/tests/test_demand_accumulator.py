"""
SentinelScale — Stage F2 Demand Observation Accumulator Tests
Tests validation, timestamp conversion, security filtering, deduplication,
chronological ordering, retention windowing, workload isolation, and persistence.
"""
import math
import time
import uuid
import pytest

from app.models.traffic_contract import TrafficAssessment, TrafficClassification
from app.services.history.demand_accumulator import (
    DemandObservationAccumulator,
    InvalidAssessmentError,
)


def create_sample_assessment(
    event_id: str | None = None,
    trace_id: str | None = None,
    timestamp: str = "2026-09-05T12:00:00Z",
    total_rps: float = 200.0,
    legitimate_rps_estimate: float = 200.0,
    suspicious_rps_estimate: float = 0.0,
    risk_score: float = 0.10,
    legitimacy_score: float = 0.90,
    confidence: float = 0.95,
    classification: TrafficClassification = TrafficClassification.LEGITIMATE,
    top_signals: list[str] | None = None,
) -> TrafficAssessment:
    """Helper creating valid TrafficAssessment fixtures."""
    return TrafficAssessment(
        event_id=event_id or str(uuid.uuid4()),
        trace_id=trace_id or f"trace-{uuid.uuid4().hex[:12]}",
        timestamp=timestamp,
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="traffic-rules-v1",
        window_seconds=60,
        total_rps=total_rps,
        legitimate_rps_estimate=legitimate_rps_estimate,
        suspicious_rps_estimate=suspicious_rps_estimate,
        risk_score=risk_score,
        legitimacy_score=legitimacy_score,
        confidence=confidence,
        classification=classification,
        top_signals=top_signals or ["legitimate_traffic_profile"],
    )


@pytest.fixture
def accumulator(tmp_path):
    """Fixture providing a fresh isolated SQLite-backed accumulator."""
    db_file = str(tmp_path / "test_demand_obs.db")
    return DemandObservationAccumulator(db_path=db_file)


# =========================================================================
# 1. Validation & Timestamp Conversion
# =========================================================================

def test_1_valid_assessment_becomes_observation(accumulator):
    """Test 1: Given a valid TrafficAssessment, verify a DemandObservation is persisted."""
    assessment = create_sample_assessment(
        timestamp="2026-09-05T12:00:00+00:00",
        legitimate_rps_estimate=200.0,
    )
    obs = accumulator.record_traffic_assessment(assessment, target_service="demo-api")

    assert obs is not None
    assert obs.rps == 200.0
    assert obs.timestamp == 1788609600.0  # 2026-09-05T12:00:00Z Unix epoch

    history = accumulator.get_historical_demand_observations(
        target_service="demo-api",
        historical_window_seconds=3600,
        now_epoch=1788609600.0 + 10,
    )
    assert len(history) == 1
    assert history[0].rps == 200.0
    assert history[0].timestamp == 1788609600.0


def test_2_timestamp_conversion_iso_to_unix(accumulator):
    """Test 2: Verify ISO-8601 string is correctly converted to Unix float timestamp."""
    # Test Z-suffixed ISO string
    epoch_z = accumulator.parse_iso_timestamp("2026-09-05T14:30:00Z")
    assert isinstance(epoch_z, float)

    # Test timezone offset ISO string
    epoch_offset = accumulator.parse_iso_timestamp("2026-09-05T14:30:00+00:00")
    assert epoch_z == epoch_offset

    # Malformed timestamp raises InvalidAssessmentError
    with pytest.raises(InvalidAssessmentError):
        accumulator.parse_iso_timestamp("invalid-date-string")

    with pytest.raises(InvalidAssessmentError):
        accumulator.parse_iso_timestamp("")


# =========================================================================
# 2. Security & Suspicious Traffic Filtering
# =========================================================================

def test_3_suspicious_assessment_filtered_out(accumulator):
    """Test 3: Verify clearly hostile / suspicious assessments are NOT accumulated as demand."""
    hostile_assessment = create_sample_assessment(
        timestamp="2026-09-05T12:00:00Z",
        total_rps=1000.0,
        legitimate_rps_estimate=100.0,
        suspicious_rps_estimate=900.0,
        risk_score=0.88,  # > 0.80 max risk threshold
        legitimacy_score=0.10,
        confidence=0.90,
        classification=TrafficClassification.MALICIOUS,
        top_signals=["critical_ip_concentration", "critical_bot_ua_signature"],
    )
    obs = accumulator.record_traffic_assessment(hostile_assessment, target_service="demo-api")

    # Filtered by policy -> returns None
    assert obs is None

    # Verify store remains completely empty
    assert accumulator.get_observation_count("demo-api") == 0


def test_4_legitimate_traffic_retained(accumulator):
    """Test 4: Verify organic legitimate traffic with low risk is stored."""
    clean_assessment = create_sample_assessment(
        timestamp="2026-09-05T12:00:00Z",
        total_rps=350.0,
        legitimate_rps_estimate=350.0,
        suspicious_rps_estimate=0.0,
        risk_score=0.05,
        legitimacy_score=0.95,
        confidence=0.90,
        classification=TrafficClassification.LEGITIMATE,
    )
    obs = accumulator.record_traffic_assessment(clean_assessment, target_service="demo-api")

    assert obs is not None
    assert obs.rps == 350.0
    assert accumulator.get_observation_count("demo-api") == 1


def test_5_invalid_rps_rejected(accumulator):
    """Test 5: Verify negative, NaN, or infinite RPS is rejected explicitly."""
    # Negative RPS
    with pytest.raises(InvalidAssessmentError):
        neg_assessment = create_sample_assessment(legitimate_rps_estimate=-50.0)
        accumulator.record_traffic_assessment(neg_assessment)

    # Infinite RPS
    with pytest.raises(InvalidAssessmentError):
        inf_assessment = create_sample_assessment(legitimate_rps_estimate=float("inf"))
        accumulator.record_traffic_assessment(inf_assessment)

    # NaN RPS
    with pytest.raises(InvalidAssessmentError):
        nan_assessment = create_sample_assessment(legitimate_rps_estimate=float("nan"))
        accumulator.record_traffic_assessment(nan_assessment)


# =========================================================================
# 3. Deduplication & Idempotency
# =========================================================================

def test_6_duplicate_assessment_deduplication(accumulator):
    """Test 6: Ingesting the exact same TrafficAssessment twice produces 1 observation."""
    assessment = create_sample_assessment(
        event_id="ev-fixed-unique-uuid-123",
        timestamp="2026-09-05T12:00:00Z",
        legitimate_rps_estimate=150.0,
    )
    obs1 = accumulator.record_traffic_assessment(assessment, target_service="demo-api")
    obs2 = accumulator.record_traffic_assessment(assessment, target_service="demo-api")

    assert obs1 is not None
    assert obs2 is not None
    assert accumulator.get_observation_count("demo-api") == 1


# =========================================================================
# 4. Ordering & Windowing
# =========================================================================

def test_7_chronological_ordering(accumulator):
    """Test 7: Out-of-order insertions are retrieved strictly ordered chronologically."""
    # Insert T3, then T1, then T2
    t1_iso = "2026-09-05T12:00:00Z"
    t2_iso = "2026-09-05T12:00:30Z"
    t3_iso = "2026-09-05T12:01:00Z"

    accumulator.record_traffic_assessment(create_sample_assessment(timestamp=t3_iso, legitimate_rps_estimate=300.0))
    accumulator.record_traffic_assessment(create_sample_assessment(timestamp=t1_iso, legitimate_rps_estimate=100.0))
    accumulator.record_traffic_assessment(create_sample_assessment(timestamp=t2_iso, legitimate_rps_estimate=200.0))

    now_ref = accumulator.parse_iso_timestamp(t3_iso) + 5
    observations = accumulator.get_historical_demand_observations(
        target_service="demo-api",
        historical_window_seconds=3600,
        now_epoch=now_ref,
    )

    assert len(observations) == 3
    # Strictly ascending
    assert observations[0].rps == 100.0
    assert observations[1].rps == 200.0
    assert observations[2].rps == 300.0
    assert observations[0].timestamp < observations[1].timestamp < observations[2].timestamp


def test_8_historical_window_filtering(accumulator):
    """Test 8: Observations outside the lookback window are excluded from retrieval."""
    t_old = "2026-09-05T10:00:00Z"  # 2 hours old
    t_recent1 = "2026-09-05T11:45:00Z"  # 15 mins old
    t_recent2 = "2026-09-05T11:55:00Z"  # 5 mins old

    accumulator.record_traffic_assessment(create_sample_assessment(timestamp=t_old, legitimate_rps_estimate=50.0))
    accumulator.record_traffic_assessment(create_sample_assessment(timestamp=t_recent1, legitimate_rps_estimate=150.0))
    accumulator.record_traffic_assessment(create_sample_assessment(timestamp=t_recent2, legitimate_rps_estimate=180.0))

    now_ref = accumulator.parse_iso_timestamp("2026-09-05T12:00:00Z")

    # 1800s (30m) lookback -> excludes t_old
    recent_obs = accumulator.get_historical_demand_observations(
        target_service="demo-api",
        historical_window_seconds=1800,
        now_epoch=now_ref,
    )

    assert len(recent_obs) == 2
    assert recent_obs[0].rps == 150.0
    assert recent_obs[1].rps == 180.0


# =========================================================================
# 5. Workload Isolation & Persistence
# =========================================================================

def test_9_workload_isolation(accumulator):
    """Test 9: Observations for one service target are strictly isolated from others."""
    a1 = create_sample_assessment(timestamp="2026-09-05T12:00:00Z", legitimate_rps_estimate=100.0)
    a2 = create_sample_assessment(timestamp="2026-09-05T12:00:10Z", legitimate_rps_estimate=250.0)

    accumulator.record_traffic_assessment(a1, target_service="demo-api")
    accumulator.record_traffic_assessment(a2, target_service="payment-gateway")

    now_ref = accumulator.parse_iso_timestamp("2026-09-05T12:00:10Z") + 10
    demo_obs = accumulator.get_historical_demand_observations(target_service="demo-api", now_epoch=now_ref)
    payment_obs = accumulator.get_historical_demand_observations(target_service="payment-gateway", now_epoch=now_ref)

    assert len(demo_obs) == 1
    assert demo_obs[0].rps == 100.0

    assert len(payment_obs) == 1
    assert payment_obs[0].rps == 250.0



def test_10_persistence_across_restarts(tmp_path):
    """Test 10: Observations survive reinitialization of the accumulator instance."""
    db_file = str(tmp_path / "persistent_history.db")

    # 1. First instance writes observation
    acc1 = DemandObservationAccumulator(db_path=db_file)
    assessment = create_sample_assessment(
        timestamp="2026-09-05T12:00:00Z",
        legitimate_rps_estimate=225.0,
    )
    acc1.record_traffic_assessment(assessment, target_service="demo-api")
    now_ref = acc1.parse_iso_timestamp("2026-09-05T12:00:00Z") + 10

    # 2. Second instance connects to same db file
    acc2 = DemandObservationAccumulator(db_path=db_file)
    restored_obs = acc2.get_historical_demand_observations(
        target_service="demo-api",
        historical_window_seconds=3600,
        now_epoch=now_ref,
    )

    assert len(restored_obs) == 1
    assert restored_obs[0].rps == 225.0
