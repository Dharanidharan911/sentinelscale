import asyncio
import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest
from fastapi.testclient import TestClient
from app.config.settings import Settings
from app.main import app
from app.models.context import DecisionContext
from app.models.decision import ScalingAction, ScalingDecision
from app.models.demand_contract import DemandForecast
from app.models.history import StoredObservation
from app.models.resource import ResourceState
from app.models.traffic_contract import TrafficAssessment
from app.services.context_aggregator import AggregationError, ContextAggregatorService
from app.services.decision_engine import DecisionEngine
from app.services.history.sqlite_store import SQLiteDecisionHistoryStore
from app.services.metrics.prometheus import PrometheusMetricsService
from app.services.observation_scheduler import ObservationSchedulerService
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.mock_provider import MockTelemetryProvider


# ==============================================================================
# Helper Mock Payloads & Providers
# ==============================================================================

def make_traffic_payload(total_rps=1200.0, legitimate_rps=1200.0, risk_score=0.1, classification="legitimate"):
    return {
        "event_id": "evt-tr-001",
        "timestamp": "2026-09-04T00:00:00Z",
        "contract_version": "1.0.0",
        "service_version": "0.1.0",
        "model_version": "rule-based-v1",
        "window_seconds": 60,
        "total_rps": total_rps,
        "legitimate_rps_estimate": legitimate_rps,
        "suspicious_rps_estimate": total_rps - legitimate_rps,
        "risk_score": risk_score,
        "legitimacy_score": 1.0 - risk_score,
        "confidence": 0.95,
        "classification": classification,
        "top_signals": [],
    }


def make_demand_payload(predicted_rps=1200.0):
    return {
        "event_id": "evt-dm-001",
        "generated_at": "2026-09-04T00:00:00Z",
        "contract_version": "1.0.0",
        "service_version": "0.1.0",
        "model_version": "forecast-v1",
        "forecast_horizon_seconds": 300,
        "predicted_legitimate_rps": predicted_rps,
        "lower_bound_rps": predicted_rps * 0.9,
        "upper_bound_rps": predicted_rps * 1.1,
        "confidence": 0.95,
    }


class HighCpuAttackTelemetryProvider(ResourceTelemetryProvider):
    """Telemetry provider simulating CPU surge during a DDoS attack."""
    def __init__(self):
        self._mock = MockTelemetryProvider()

    @property
    def provider_name(self) -> str:
        return "attack-mock"

    async def fetch_resource_state(self, namespace: str, workload: str, trace_id: str | None = None) -> ResourceState:
        state = await self._mock.fetch_resource_state(namespace, workload, trace_id)
        return state.model_copy(update={
            "cpu_utilization": 0.95,
            "request_rate": 6000.0,
            "running_pods": 4,
            "desired_pods": 4,
        })


class AsyncMockTransport(httpx.AsyncBaseTransport):
    """Controlled async HTTP transport for mocking upstream microservices."""
    def __init__(self, handler):
        self.handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.handler(request)


# ==============================================================================
# 1. End-to-End Pipeline Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_e2e_pipeline_legitimate_demand_surge():
    """
    Scenario A: Legitimate Demand Surge
    Demand increases (2800 predicted RPS), low attack risk (0.05).
    Pipeline evaluates SCALE to 8 pods, persists history, updates metrics with 0 Kubernetes mutation.
    """
    metrics = PrometheusMetricsService()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_e2e_surge.db")
        history = SQLiteDecisionHistoryStore(db_path=db_path)
        try:
            async def mock_traffic_handler(req: httpx.Request):
                data = make_traffic_payload(total_rps=2800.0, legitimate_rps=2800.0, risk_score=0.05)
                data["trace_id"] = req.headers.get("X-Trace-ID", "tr-surge-01")
                return httpx.Response(200, json=data)

            async def mock_demand_handler(req: httpx.Request):
                data = make_demand_payload(predicted_rps=2800.0)
                data["trace_id"] = req.headers.get("X-Trace-ID", "tr-surge-01")
                return httpx.Response(200, json=data)

            from app.clients.traffic_client import TrafficIntelligenceClient
            from app.clients.demand_client import DemandIntelligenceClient

            traffic_client = TrafficIntelligenceClient(
                http_client=httpx.AsyncClient(transport=AsyncMockTransport(mock_traffic_handler))
            )
            demand_client = DemandIntelligenceClient(
                http_client=httpx.AsyncClient(transport=AsyncMockTransport(mock_demand_handler))
            )

            resource_observer = ResourceObserverService(provider=MockTelemetryProvider())
            aggregator = ContextAggregatorService(
                traffic_client=traffic_client,
                demand_client=demand_client,
                resource_observer=resource_observer,
                decision_engine=DecisionEngine(),
            )

            scheduler = ObservationSchedulerService(
                aggregator=aggregator,
                history_store=history,
                metrics=metrics,
                interval_seconds=1.0,
            )

            # Execute scheduled cycle
            res = await scheduler.execute_evaluation(trace_id="trace-surge-e2e-01")

            # 1. Verify Decision
            assert res is not None
            assert res.success is True
            decision = res.scaling_decision
            assert decision.action == ScalingAction.SCALE
            assert decision.recommended_pods == 8
            assert decision.current_pods == 4
            assert decision.dry_run is True
            assert decision.shadow_mode is True

            # 2. Verify History Persistence
            hist_records = history.get_by_trace_id("trace-surge-e2e-01")
            assert len(hist_records) == 1
            rec = hist_records[0]
            assert rec.success is True
            assert rec.action == ScalingAction.SCALE
            assert rec.recommended_pods == 8
            assert rec.trace_id == "trace-surge-e2e-01"

            # 3. Verify Metrics Exposition
            metrics_text = metrics.export_prometheus_text()
            assert 'sentinelscale_observations_total{status="success"} 1.0' in metrics_text
            assert 'sentinelscale_decisions_total{action="SCALE"} 1.0' in metrics_text
            assert "sentinelscale_sentinelscale_recommendation_pods 8.0" in metrics_text
            assert "sentinelscale_traffic_risk 0.05" in metrics_text
            assert "trace-surge-e2e-01" not in metrics_text  # Strict low cardinality

        finally:
            history.close()


@pytest.mark.asyncio
async def test_e2e_pipeline_attack_heavy_scenario():
    """
    Scenario B: Attack-Heavy Scenario
    Total traffic = 6000 RPS, legitimate = 1200 RPS, current capacity = 1400 RPS (4 pods), risk = 0.85.
    Reactive HPA baseline would scale to 6 pods due to 95% CPU spike; SentinelScale HOLDs at 4 pods.
    """
    metrics = PrometheusMetricsService()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_e2e_attack.db")
        history = SQLiteDecisionHistoryStore(db_path=db_path)
        try:
            async def mock_traffic_handler(req: httpx.Request):
                data = make_traffic_payload(total_rps=6000.0, legitimate_rps=1200.0, risk_score=0.85, classification="malicious")
                data["trace_id"] = req.headers.get("X-Trace-ID", "tr-attack-01")
                return httpx.Response(200, json=data)

            async def mock_demand_handler(req: httpx.Request):
                data = make_demand_payload(predicted_rps=1200.0)
                data["trace_id"] = req.headers.get("X-Trace-ID", "tr-attack-01")
                return httpx.Response(200, json=data)

            from app.clients.traffic_client import TrafficIntelligenceClient
            from app.clients.demand_client import DemandIntelligenceClient

            traffic_client = TrafficIntelligenceClient(
                http_client=httpx.AsyncClient(transport=AsyncMockTransport(mock_traffic_handler))
            )
            demand_client = DemandIntelligenceClient(
                http_client=httpx.AsyncClient(transport=AsyncMockTransport(mock_demand_handler))
            )

            aggregator = ContextAggregatorService(
                traffic_client=traffic_client,
                demand_client=demand_client,
                resource_observer=ResourceObserverService(provider=HighCpuAttackTelemetryProvider()),
                decision_engine=DecisionEngine(),
            )

            scheduler = ObservationSchedulerService(
                aggregator=aggregator,
                history_store=history,
                metrics=metrics,
            )

            res = await scheduler.execute_evaluation(trace_id="trace-attack-e2e-01")

            assert res is not None
            assert res.success is True
            decision = res.scaling_decision
            assert decision.action == ScalingAction.HOLD
            assert decision.recommended_pods == 4
            assert decision.baseline_hpa_recommended_pods == 6  # HPA would reactively scale out
            assert decision.pod_delta_vs_baseline == -2  # SentinelScale saved 2 pods of overprovisioning!
            assert decision.dry_run is True

            # Verify history & metrics
            records = history.get_by_trace_id("trace-attack-e2e-01")
            assert len(records) == 1
            assert records[0].action == ScalingAction.HOLD
            assert records[0].pod_delta_vs_baseline == -2

            metrics_text = metrics.export_prometheus_text()
            assert 'sentinelscale_decisions_total{action="HOLD"} 1.0' in metrics_text
            assert 'sentinelscale_decision_reasons_total{reason_category="ATTACK_MITIGATION"} 1.0' in metrics_text
            assert "sentinelscale_baseline_hpa_divergence_pods -2.0" in metrics_text

        finally:
            history.close()


@pytest.mark.asyncio
async def test_e2e_pipeline_low_demand_scale_down():
    """
    Scenario C: Low Demand Scale Down
    Predicted legitimate demand = 350 RPS (down from 1400 RPS capacity, 4 pods).
    Pipeline evaluates SCALE down to 2 pods (bounded by min_pods=2).
    """
    metrics = PrometheusMetricsService()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_e2e_low.db")
        history = SQLiteDecisionHistoryStore(db_path=db_path)
        try:
            async def mock_traffic_handler(req: httpx.Request):
                data = make_traffic_payload(total_rps=350.0, legitimate_rps=350.0, risk_score=0.05)
                data["trace_id"] = req.headers.get("X-Trace-ID", "tr-low-01")
                return httpx.Response(200, json=data)

            async def mock_demand_handler(req: httpx.Request):
                data = make_demand_payload(predicted_rps=350.0)
                data["trace_id"] = req.headers.get("X-Trace-ID", "tr-low-01")
                return httpx.Response(200, json=data)

            from app.clients.traffic_client import TrafficIntelligenceClient
            from app.clients.demand_client import DemandIntelligenceClient

            traffic_client = TrafficIntelligenceClient(
                http_client=httpx.AsyncClient(transport=AsyncMockTransport(mock_traffic_handler))
            )
            demand_client = DemandIntelligenceClient(
                http_client=httpx.AsyncClient(transport=AsyncMockTransport(mock_demand_handler))
            )

            aggregator = ContextAggregatorService(
                traffic_client=traffic_client,
                demand_client=demand_client,
                resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
                decision_engine=DecisionEngine(),
            )

            scheduler = ObservationSchedulerService(
                aggregator=aggregator,
                history_store=history,
                metrics=metrics,
            )

            res = await scheduler.execute_evaluation(trace_id="trace-low-e2e-01")

            assert res.success is True
            decision = res.scaling_decision
            assert decision.action == ScalingAction.SCALE
            assert decision.recommended_pods == 2  # Scaled down to min_pods
            assert decision.current_pods == 4

        finally:
            history.close()


# ==============================================================================
# 2. Failure Propagation, Error Isolation & Recovery Sequence
# ==============================================================================

@pytest.mark.asyncio
async def test_failure_propagation_and_recovery_sequence():
    """
    Validates the failure recovery cycle:
    1. Success
    2. Traffic Intelligence failure (HTTP 502)
    3. Demand Intelligence timeout
    4. Recovery -> Success
    Verifies that scheduler stays alive, history records both successes and failures,
    and metrics track upstream errors without permanent poisoning.
    """
    metrics = PrometheusMetricsService()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_recovery.db")
        history = SQLiteDecisionHistoryStore(db_path=db_path)
        try:
            state = {"mode": "success"}

            async def mock_traffic(req: httpx.Request):
                if state["mode"] == "traffic_error":
                    return httpx.Response(502, text="Traffic Intelligence 502 Bad Gateway")
                data = make_traffic_payload()
                data["trace_id"] = req.headers.get("X-Trace-ID", "tr-rec")
                return httpx.Response(200, json=data)

            async def mock_demand(req: httpx.Request):
                if state["mode"] == "demand_timeout":
                    raise httpx.ReadTimeout("Request timed out after 5.0s")
                data = make_demand_payload()
                data["trace_id"] = req.headers.get("X-Trace-ID", "tr-rec")
                return httpx.Response(200, json=data)

            from app.clients.traffic_client import TrafficIntelligenceClient
            from app.clients.demand_client import DemandIntelligenceClient

            traffic_client = TrafficIntelligenceClient(
                http_client=httpx.AsyncClient(transport=AsyncMockTransport(mock_traffic))
            )
            demand_client = DemandIntelligenceClient(
                http_client=httpx.AsyncClient(transport=AsyncMockTransport(mock_demand))
            )

            aggregator = ContextAggregatorService(
                traffic_client=traffic_client,
                demand_client=demand_client,
                resource_observer=ResourceObserverService(provider=MockTelemetryProvider()),
                decision_engine=DecisionEngine(),
            )

            scheduler = ObservationSchedulerService(
                aggregator=aggregator,
                history_store=history,
                metrics=metrics,
            )

            # Step 1: Initial Success
            state["mode"] = "success"
            r1 = await scheduler.execute_evaluation(trace_id="tr-step-1")
            assert r1.success is True
            assert scheduler.evaluation_count == 1
            assert scheduler.failure_count == 0

            # Step 2: Traffic Intelligence Failure
            state["mode"] = "traffic_error"
            r2 = await scheduler.execute_evaluation(trace_id="tr-step-2")
            assert r2.success is False
            assert scheduler.evaluation_count == 1
            assert scheduler.failure_count == 1

            # Step 3: Demand Intelligence Timeout
            state["mode"] = "demand_timeout"
            r3 = await scheduler.execute_evaluation(trace_id="tr-step-3")
            assert r3.success is False
            assert scheduler.evaluation_count == 1
            assert scheduler.failure_count == 2

            # Step 4: Upstream Recovery -> Success
            state["mode"] = "success"
            r4 = await scheduler.execute_evaluation(trace_id="tr-step-4")
            assert r4.success is True
            assert scheduler.evaluation_count == 2
            assert scheduler.failure_count == 2

            # Verify History Record Counts
            stats = history.get_stats()
            assert stats.total_observations == 4
            assert stats.successful_observations == 2
            assert stats.failed_observations == 2

            # Verify Metrics Failure Counters
            metrics_text = metrics.export_prometheus_text()
            assert 'sentinelscale_observations_total{status="success"} 2.0' in metrics_text
            assert 'sentinelscale_observations_total{status="failure"} 2.0' in metrics_text
            assert 'sentinelscale_upstream_failures_total{error_type="bad_gateway",service="traffic_intelligence"} 1.0' in metrics_text
            assert 'sentinelscale_upstream_failures_total{error_type="timeout",service="demand_intelligence"} 1.0' in metrics_text

        finally:
            history.close()


# ==============================================================================
# 3. Single-Flight & Scheduler Timeout Protection
# ==============================================================================

@pytest.mark.asyncio
async def test_scheduler_single_flight_and_metric_increment():
    """
    Verify that concurrent triggers during an ongoing evaluation are skipped
    and increment sentinelscale_scheduler_observations_skipped_total.
    """
    metrics = PrometheusMetricsService()
    eval_started = asyncio.Event()
    eval_release = asyncio.Event()

    async def slow_orchestrate(*args, **kwargs):
        eval_started.set()
        await eval_release.wait()
        return ScalingDecision(
            decision_id="dec-1",
            event_id="evt-1",
            trace_id="tr-1",
            timestamp="2026-09-04T00:00:00Z",
            contract_version="1.0.0",
            service_version="0.1.0",
            model_version="test",
            action=ScalingAction.HOLD,
            reason="Test",
            confidence=0.9,
            traffic_risk=0.1,
            predicted_legitimate_rps=1000.0,
            current_capacity_rps=1400.0,
            current_pods=4,
            recommended_pods=4,
            baseline_hpa_recommended_pods=4,
            pod_delta_vs_baseline=0,
            policy="test",
            dry_run=True,
            shadow_mode=True,
        )

    mock_agg = MagicMock(spec=ContextAggregatorService)
    mock_agg.orchestrate_decision = AsyncMock(side_effect=slow_orchestrate)

    scheduler = ObservationSchedulerService(
        aggregator=mock_agg,
        metrics=metrics,
    )

    task1 = asyncio.create_task(scheduler.execute_evaluation(trace_id="tr-run-1"))
    await eval_started.wait()

    # Attempt concurrent trigger while task1 is running
    res2 = await scheduler.execute_evaluation(trace_id="tr-run-2")
    assert res2 is None  # Skipped!

    eval_release.set()
    res1 = await task1
    assert res1.success is True

    metrics_text = metrics.export_prometheus_text()
    assert "sentinelscale_scheduler_observations_skipped_total 1.0" in metrics_text


# ==============================================================================
# 4. HTTP Read-Only Endpoints & Safety Invariants
# ==============================================================================

client = TestClient(app)


def test_metrics_and_history_endpoints_are_read_only():
    """
    Verify that GET /metrics, GET /api/v1/history, and GET /version are strictly read-only
    and do not trigger evaluations or mutate any cluster state.
    """
    # 1. Version endpoint
    v_res = client.get("/version")
    assert v_res.status_code == 200
    v_data = v_res.json()
    assert v_data["dry_run"] is True
    assert v_data["shadow_mode"] is True
    assert v_data["autonomous_actions_enabled"] is False

    # 2. Metrics endpoint
    m_res = client.get("/metrics")
    assert m_res.status_code == 200
    assert "text/plain" in m_res.headers["content-type"]
    assert "sentinelscale_observations_total" in m_res.text

    # 3. History endpoints
    h_res = client.get("/api/v1/history?limit=5")
    assert h_res.status_code == 200
    assert isinstance(h_res.json(), list)

    stats_res = client.get("/api/v1/history/stats")
    assert stats_res.status_code == 200
    assert "total_observations" in stats_res.json()

