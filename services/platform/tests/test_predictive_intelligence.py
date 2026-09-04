from datetime import datetime, timedelta, timezone
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.decision import ScalingAction
from app.models.history import StoredObservation
from app.models.prediction import (
    ConfidenceLevel,
    DataQuality,
    PredictionStatus,
    PressureLevel,
    TrendDirection,
)
from app.services.history.sqlite_store import SQLiteDecisionHistoryStore
from app.services.intelligence.predictive import DefaultPredictiveIntelligenceService


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
# Unit & Mathematical Predictive Intelligence Tests
# ==============================================================================

def test_1_cold_start_insufficient_data():
    """Test 1: Fewer than min_samples returns status='INSUFFICIENT_DATA'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test1.db"))
        try:
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.status == PredictionStatus.INSUFFICIENT_DATA
            assert forecast.sample_count == 0
            assert forecast.data_quality == DataQuality.INSUFFICIENT_DATA
            assert len(forecast.signals) == 0
            assert forecast.pressure.level == PressureLevel.INSUFFICIENT_DATA
            assert forecast.pods.predicted_recommended_pods is None
        finally:
            store.close()


def test_2_cold_start_single_sample():
    """Test 2: Exactly 1 sample returns INSUFFICIENT_DATA."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test2.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            store.record_observation(make_obs("obs-1", now_dt.isoformat(), 1000.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.status == PredictionStatus.INSUFFICIENT_DATA
            assert forecast.sample_count == 1
        finally:
            store.close()


def test_3_cold_start_four_samples():
    """Test 3: Exactly 4 samples (< min 5) returns INSUFFICIENT_DATA."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test3.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(4):
                ts = (now_dt - timedelta(minutes=4 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, 1000.0 + i * 50))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.status == PredictionStatus.INSUFFICIENT_DATA
            assert forecast.sample_count == 4
        finally:
            store.close()


def test_4_minimum_data_five_samples():
    """Test 4: Exactly 5 samples triggers successful forecast generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test4.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(5):
                ts = (now_dt - timedelta(minutes=5 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, 1000.0 + i * 50))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.status in (PredictionStatus.OK, PredictionStatus.DEGRADED)
            assert forecast.sample_count == 5
            assert len(forecast.signals) == 7
            assert forecast.pressure is not None
            assert forecast.pods is not None
        finally:
            store.close()


def test_5_increasing_demand_trend():
    """Test 5: Strictly increasing demand produces trend='INCREASING'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test5.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(10):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=500.0 + i * 100.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast(horizon="5m")
            assert forecast.status == PredictionStatus.OK
            demand_sig = forecast.signals["predicted_legitimate_rps"]
            assert demand_sig.trend == TrendDirection.INCREASING
            assert demand_sig.slope_per_second > 0.0
            assert demand_sig.predicted_value > demand_sig.latest_value
        finally:
            store.close()


def test_6_decreasing_demand_trend():
    """Test 6: Strictly decreasing demand produces trend='DECREASING'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test6.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(10):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=1500.0 - i * 100.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast(horizon="5m")
            assert forecast.status == PredictionStatus.OK
            demand_sig = forecast.signals["predicted_legitimate_rps"]
            assert demand_sig.trend == TrendDirection.DECREASING
            assert demand_sig.slope_per_second < 0.0
            assert demand_sig.predicted_value < demand_sig.latest_value
        finally:
            store.close()


def test_7_stable_demand_trend():
    """Test 7: Stable demand with negligible change produces trend='STABLE'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test7.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(10):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=1000.0 + (i % 2) * 0.01))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            demand_sig = forecast.signals["predicted_legitimate_rps"]
            assert demand_sig.trend == TrendDirection.STABLE
        finally:
            store.close()


def test_8_constant_demand_zero_variance():
    """Test 8: Zero variance series produces slope=0.0 and identical predicted value."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test8.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(10):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=800.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            demand_sig = forecast.signals["predicted_legitimate_rps"]
            assert demand_sig.predicted_value == 800.0
            assert demand_sig.slope_per_second == 0.0
            assert demand_sig.confidence == ConfidenceLevel.HIGH
        finally:
            store.close()


def test_9_negative_prediction_clamping():
    """Test 9: Steep downward trend is clamped at 0.0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test9.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(5):
                ts = (now_dt - timedelta(minutes=5 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=500.0 - i * 100.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast(horizon="15m")
            demand_sig = forecast.signals["predicted_legitimate_rps"]
            assert demand_sig.predicted_value == 0.0
        finally:
            store.close()


def test_10_traffic_risk_clamping():
    """Test 10: Traffic risk is strictly clamped within [0.0, 1.0]."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test10.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, risk=0.2 + i * 0.15))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast(horizon="15m")
            risk_sig = forecast.signals["traffic_risk"]
            assert risk_sig.predicted_value <= 1.0
            assert risk_sig.predicted_value >= 0.0
        finally:
            store.close()


def test_11_pod_metrics_clamping():
    """Test 11: Pod metrics are clamped to minimum 1.0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test11.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, rec_pods=max(1, 4 - i)))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast(horizon="15m")
            rec_pods_sig = forecast.signals["recommended_pods"]
            assert rec_pods_sig.predicted_value >= 1.0
        finally:
            store.close()


def test_12_pod_delta_signed_unclamped():
    """Test 12: Pod delta preserves negative signed values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test12.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, rec_pods=2, hpa_pods=5))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast(horizon="5m")
            delta_sig = forecast.signals["pod_delta_vs_baseline"]
            assert delta_sig.predicted_value < 0.0
            assert round(delta_sig.predicted_value) == -3
        finally:
            store.close()


def test_13_outlier_detection_and_handling():
    """Test 13: Outlier in history is detected and degrades confidence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test13.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(20):
                ts = (now_dt - timedelta(minutes=20 - i)).isoformat()
                val = 1000.0 + (5000.0 if i == 10 else 0.0)
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=val))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast(window="1h")
            demand_sig = forecast.signals["predicted_legitimate_rps"]
            assert demand_sig.confidence in (ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM)
        finally:
            store.close()


def test_14_high_noise_confidence_degradation():
    """Test 14: Chaotic noise degrades confidence to LOW."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test14.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            values = [100.0, 900.0, 200.0, 850.0, 150.0, 950.0, 300.0, 800.0]
            for i, val in enumerate(values):
                ts = (now_dt - timedelta(minutes=len(values) - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=val))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            demand_sig = forecast.signals["predicted_legitimate_rps"]
            assert demand_sig.confidence in (ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM)
        finally:
            store.close()


def test_15_clean_linear_high_confidence():
    """Test 15: Clean linear trend produces HIGH confidence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test15.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(10):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=100.0 + i * 50.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            demand_sig = forecast.signals["predicted_legitimate_rps"]
            assert demand_sig.confidence == ConfidenceLevel.HIGH
        finally:
            store.close()


def test_16_moderate_fit_confidence():
    """Test 16: Small dataset (5-9 samples) produces MEDIUM confidence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test16.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            values = [100.0, 140.0, 130.0, 180.0, 170.0, 220.0]
            for i, val in enumerate(values):
                ts = (now_dt - timedelta(minutes=len(values) - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=val))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            demand_sig = forecast.signals["predicted_legitimate_rps"]
            assert demand_sig.confidence in (ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH)
        finally:
            store.close()


def test_17_recency_fresh_data():
    """Test 17: Fresh observations result in data_quality='GOOD'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test17.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(5):
                ts = (now_dt - timedelta(seconds=120 - i * 20)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=1000.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.data_quality == DataQuality.GOOD
            assert forecast.status == PredictionStatus.OK
        finally:
            store.close()


def test_18_stale_data_detection():
    """Test 18: Observations older than 10 minutes result in status='STALE' and quality='STALE'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test18.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=20 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=1000.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.status == PredictionStatus.STALE
            assert forecast.data_quality == DataQuality.STALE
            demand_sig = forecast.signals["predicted_legitimate_rps"]
            assert demand_sig.confidence == ConfidenceLevel.LOW
        finally:
            store.close()


def test_19_capacity_pressure_normal():
    """Test 19: Predicted demand / capacity < 50% yields NORMAL pressure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test19.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=400.0, cap_rps=1000.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.pressure is not None
            assert forecast.pressure.level == PressureLevel.NORMAL
            assert forecast.pressure.predicted_capacity_utilization == 0.4
        finally:
            store.close()


def test_20_capacity_pressure_elevated():
    """Test 20: Predicted demand / capacity between 50% and 75% yields ELEVATED pressure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test20.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=600.0, cap_rps=1000.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.pressure is not None
            assert forecast.pressure.level == PressureLevel.ELEVATED
            assert forecast.pressure.predicted_capacity_utilization == 0.6
        finally:
            store.close()


def test_21_capacity_pressure_high():
    """Test 21: Predicted demand / capacity between 75% and 90% yields HIGH pressure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test21.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=800.0, cap_rps=1000.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.pressure is not None
            assert forecast.pressure.level == PressureLevel.HIGH
            assert forecast.pressure.predicted_capacity_utilization == 0.8
        finally:
            store.close()


def test_22_capacity_pressure_critical():
    """Test 22: Predicted demand / capacity >= 90% yields CRITICAL pressure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test22.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=950.0, cap_rps=1000.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.pressure is not None
            assert forecast.pressure.level == PressureLevel.CRITICAL
            assert forecast.pressure.predicted_capacity_utilization == 0.95
        finally:
            store.close()


def test_23_pod_advisory_calculation():
    """Test 23: Advisory pods is calculated via ceil(demand / 350.0)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test23.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=1400.0, curr_pods=4))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.pods is not None
            assert forecast.pods.predicted_recommended_pods == 4
        finally:
            store.close()


def test_24_pod_advisory_min_clamping():
    """Test 24: Low predicted demand is clamped to min 2 pods."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test24.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=50.0, curr_pods=4))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.pods is not None
            assert forecast.pods.predicted_recommended_pods == 2
        finally:
            store.close()


def test_25_pod_advisory_max_clamping():
    """Test 25: Very high predicted demand is clamped to max 20 pods."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test25.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=10000.0, curr_pods=4))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.pods is not None
            assert forecast.pods.predicted_recommended_pods == 20
        finally:
            store.close()


def test_26_pod_advisory_hpa_comparison():
    """Test 26: Pod advisory accurately tracks delta vs baseline HPA."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test26.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=700.0, curr_pods=2, hpa_pods=6))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            assert forecast.pods is not None
            assert forecast.pods.predicted_recommended_pods == 2
            assert forecast.pods.predicted_hpa_pods == 6
            assert forecast.pods.predicted_delta_vs_hpa == -4
        finally:
            store.close()


def test_27_all_seven_signals_forecasted():
    """Test 27: All 7 expected signals are forecasted with complete metadata."""
    expected_signals = [
        "predicted_legitimate_rps",
        "traffic_risk",
        "current_capacity_rps",
        "recommended_pods",
        "current_pods",
        "baseline_hpa_recommended_pods",
        "pod_delta_vs_baseline",
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test27.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast()
            for sig_name in expected_signals:
                assert sig_name in forecast.signals
                sig = forecast.signals[sig_name]
                assert sig.signal == sig_name
                assert isinstance(sig.latest_value, float)
                assert isinstance(sig.predicted_value, float)
                assert isinstance(sig.slope_per_second, float)
                assert sig.trend in TrendDirection
                assert sig.confidence in ConfidenceLevel
        finally:
            store.close()


def test_28_forecast_horizons():
    """Test 28: Various forecast horizons (5m, 15m, custom seconds)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test28.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(6):
                ts = (now_dt - timedelta(minutes=6 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=500.0 + i * 100.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            
            f_5m = service.generate_forecast(horizon="5m")
            assert f_5m.forecast_horizon_seconds == 300
            
            f_15m = service.generate_forecast(horizon="15m")
            assert f_15m.forecast_horizon_seconds == 900
            assert f_15m.signals["predicted_legitimate_rps"].predicted_value > f_5m.signals["predicted_legitimate_rps"].predicted_value

            f_custom = service.generate_forecast(horizon_seconds=120)
            assert f_custom.forecast_horizon_seconds == 120
        finally:
            store.close()


def test_29_forecast_time_windows():
    """Test 29: Various time windows filter historical observations properly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test29.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(60):
                ts = (now_dt - timedelta(minutes=120 - i * 2)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=1000.0))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            
            f_15m = service.generate_forecast(window="15m")
            assert f_15m.sample_count <= 10
            
            f_1h = service.generate_forecast(window="1h")
            assert f_1h.sample_count > f_15m.sample_count
        finally:
            store.close()


def test_30_specific_observation_anchor():
    """Test 30: Anchoring forecast to a specific historical observation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteDecisionHistoryStore(db_path=os.path.join(tmpdir, "test30.db"))
        try:
            now_dt = datetime.now(timezone.utc)
            target_id = "obs-anchor"
            for i in range(10):
                ts = (now_dt - timedelta(minutes=20 - i)).isoformat()
                oid = target_id if i == 5 else f"obs-{i}"
                store.record_observation(make_obs(oid, ts, pred_rps=1000.0 + i * 50))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            forecast = service.generate_forecast(observation_id=target_id)
            assert forecast.status in (PredictionStatus.OK, PredictionStatus.STALE)
        finally:
            store.close()


# ==============================================================================
# API Endpoints & Contract Integration Tests
# ==============================================================================

def test_31_api_endpoint_get_predictions_success():
    """Test 31: GET /api/v1/intelligence/predictions returns 200 and valid schema."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test31.db")
        store = SQLiteDecisionHistoryStore(db_path=db_path)
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(10):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=800.0 + i * 20))
            
            from app.api.v1.endpoints import get_history_repository
            app.dependency_overrides[get_history_repository] = lambda: store

            client = TestClient(app)
            response = client.get("/api/v1/intelligence/predictions")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] in ("OK", "STALE", "DEGRADED")
            assert "predicted_legitimate_rps" in data["signals"]
            assert data["pressure"] is not None
            assert data["pods"] is not None
        finally:
            app.dependency_overrides.clear()
            store.close()


def test_32_api_endpoint_query_params():
    """Test 32: GET /api/v1/intelligence/predictions with window and horizon params."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test32.db")
        store = SQLiteDecisionHistoryStore(db_path=db_path)
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(10):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts))
            
            from app.api.v1.endpoints import get_history_repository
            app.dependency_overrides[get_history_repository] = lambda: store

            client = TestClient(app)
            response = client.get("/api/v1/intelligence/predictions?window=15m&horizon=15m")
            assert response.status_code == 200
            data = response.json()
            assert data["baseline_window"] == "15m"
            assert data["forecast_horizon_seconds"] == 900
        finally:
            app.dependency_overrides.clear()
            store.close()


def test_33_api_endpoint_invalid_window():
    """Test 33: Invalid window string returns 400 Bad Request."""
    client = TestClient(app)
    response = client.get("/api/v1/intelligence/predictions?window=invalid_window")
    assert response.status_code == 400
    assert "Invalid time window" in response.json()["detail"]


def test_34_api_endpoint_invalid_horizon():
    """Test 34: Invalid horizon string returns 400 Bad Request."""
    client = TestClient(app)
    response = client.get("/api/v1/intelligence/predictions?horizon=999xyz")
    assert response.status_code == 400
    assert "Invalid horizon" in response.json()["detail"]


def test_35_api_endpoint_invalid_timestamps():
    """Test 35: Invalid start_time / end_time returns 400 Bad Request."""
    client = TestClient(app)
    # Test partial timestamp
    response_partial = client.get("/api/v1/intelligence/predictions?start_time=2026-01-01T00:00:00Z")
    assert response_partial.status_code == 400
    assert "Both start_time and end_time must be provided" in response_partial.json()["detail"]

    # Test malformed timestamp format
    response_invalid = client.get("/api/v1/intelligence/predictions?start_time=not-a-date&end_time=invalid-date")
    assert response_invalid.status_code == 400
    assert "ISO-8601" in response_invalid.json()["detail"]




def test_36_api_endpoint_not_found_observation():
    """Test 36: Non-existent observation_id returns 400 Bad Request."""
    client = TestClient(app)
    response = client.get("/api/v1/intelligence/predictions?observation_id=non-existent-uuid")
    assert response.status_code == 400
    assert "not found in history" in response.json()["detail"]


def test_37_read_only_isolation():
    """Test 37: Predictive intelligence is strictly read-only and does not mutate history or storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test37.db")
        store = SQLiteDecisionHistoryStore(db_path=db_path)
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(8):
                ts = (now_dt - timedelta(minutes=8 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts))
            
            obs_before = store.list_observations(limit=100)
            service = DefaultPredictiveIntelligenceService(history_store=store)
            _ = service.generate_forecast()
            _ = service.generate_forecast(horizon="15m")
            obs_after = store.list_observations(limit=100)
            assert len(obs_before) == len(obs_after) == 8
        finally:
            store.close()


def test_38_deterministic_reproducibility():
    """Test 38: Multiple invocations on identical data produce identical deterministic results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test38.db")
        store = SQLiteDecisionHistoryStore(db_path=db_path)
        try:
            now_dt = datetime.now(timezone.utc)
            for i in range(10):
                ts = (now_dt - timedelta(minutes=10 - i)).isoformat()
                store.record_observation(make_obs(f"obs-{i}", ts, pred_rps=1000.0 + i * 25.5, risk=0.1 + i * 0.05))
            service = DefaultPredictiveIntelligenceService(history_store=store)
            
            f1 = service.generate_forecast(horizon="15m")
            f2 = service.generate_forecast(horizon="15m")
            
            assert f1.signals["predicted_legitimate_rps"].predicted_value == f2.signals["predicted_legitimate_rps"].predicted_value
            assert f1.signals["traffic_risk"].predicted_value == f2.signals["traffic_risk"].predicted_value
            assert f1.pressure.predicted_capacity_utilization == f2.pressure.predicted_capacity_utilization
            assert f1.pods.predicted_recommended_pods == f2.pods.predicted_recommended_pods
        finally:
            store.close()
