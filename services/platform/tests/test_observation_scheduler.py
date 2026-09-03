import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from pydantic import ValidationError
from app.config.settings import Settings
from app.models.decision import ScalingAction, ScalingDecision
from app.services.context_aggregator import AggregationError, ContextAggregatorService
from app.services.observation_scheduler import ObservationResult, ObservationSchedulerService


def make_mock_decision(action=ScalingAction.HOLD, recommended_pods=4, trace_id="trace-test-01"):
    return ScalingDecision(
        decision_id="dec-sched-01",
        event_id="evt-sched-01",
        trace_id=trace_id,
        timestamp="2026-09-03T18:00:00Z",
        contract_version="1.0.0",
        service_version="0.1.0",
        model_version="policy-rules-v0",
        action=action,
        reason="Scheduled test evaluation",
        confidence=0.91,
        traffic_risk=0.84,
        predicted_legitimate_rps=1200.0,
        current_capacity_rps=1400.0,
        current_pods=4,
        recommended_pods=recommended_pods,
        baseline_hpa_recommended_pods=4,
        pod_delta_vs_baseline=0,
        policy="default-safe-guardrail-v1",
        dry_run=True,
        shadow_mode=True,
    )


# ==============================================================================
# 1. Configuration Tests
# ==============================================================================

def test_scheduler_configuration_defaults():
    """Test default scheduler settings."""
    settings = Settings()
    assert settings.OBSERVATION_SCHEDULER_ENABLED is False
    assert settings.OBSERVATION_INTERVAL_SECONDS == 15.0
    assert settings.OBSERVATION_TARGET_NAMESPACE == "sentinelscale"
    assert settings.OBSERVATION_TARGET_WORKLOAD == "demo-api"
    assert settings.OBSERVATION_EVALUATION_TIMEOUT_SECONDS == 10.0


def test_scheduler_configuration_invalid_interval_rejected():
    """Verify that non-positive interval values raise validation errors."""
    with pytest.raises(ValidationError):
        Settings(OBSERVATION_INTERVAL_SECONDS=0.0)

    with pytest.raises(ValidationError):
        Settings(OBSERVATION_INTERVAL_SECONDS=-5.0)


# ==============================================================================
# 2. Scheduler Lifecycle Tests (Start, Stop, Cancellation)
# ==============================================================================

@pytest.mark.asyncio
async def test_scheduler_start_and_stop_lifecycle():
    """Test clean startup, running state, and graceful cancellation."""
    mock_aggregator = MagicMock(spec=ContextAggregatorService)
    mock_aggregator.orchestrate_decision = AsyncMock(return_value=make_mock_decision())

    scheduler = ObservationSchedulerService(
        aggregator=mock_aggregator,
        interval_seconds=0.05,
    )

    assert scheduler.is_running is False
    assert scheduler.evaluation_count == 0

    await scheduler.start()
    assert scheduler.is_running is True

    # Allow background loop to execute
    await asyncio.sleep(0.12)

    await scheduler.stop()
    assert scheduler.is_running is False
    assert scheduler.evaluation_count >= 2


@pytest.mark.asyncio
async def test_scheduler_idempotent_start_stop():
    """Verify calling start or stop multiple times is completely safe."""
    mock_aggregator = MagicMock(spec=ContextAggregatorService)
    mock_aggregator.orchestrate_decision = AsyncMock(return_value=make_mock_decision())

    scheduler = ObservationSchedulerService(
        aggregator=mock_aggregator,
        interval_seconds=1.0,
    )

    await scheduler.start()
    await scheduler.start()  # Idempotent start
    assert scheduler.is_running is True

    await scheduler.stop()
    await scheduler.stop()  # Idempotent stop
    assert scheduler.is_running is False


# ==============================================================================
# 3. Non-Overlapping Single-Flight Evaluation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_non_overlapping_evaluations_skips_when_locked():
    """
    Verify that if an evaluation is currently running, subsequent trigger attempts
    are skipped safely without spawning concurrent evaluations.
    """
    eval_started = asyncio.Event()
    eval_can_finish = asyncio.Event()

    async def slow_orchestrate(*args, **kwargs):
        eval_started.set()
        await eval_can_finish.wait()
        return make_mock_decision()

    mock_aggregator = MagicMock(spec=ContextAggregatorService)
    mock_aggregator.orchestrate_decision = AsyncMock(side_effect=slow_orchestrate)

    scheduler = ObservationSchedulerService(
        aggregator=mock_aggregator,
        interval_seconds=10.0,
    )

    # 1. Start Evaluation 1 in background
    task1 = asyncio.create_task(scheduler.execute_evaluation(trace_id="trace-eval-1"))
    await eval_started.wait()

    # 2. Attempt Evaluation 2 while Evaluation 1 is still in progress
    result2 = await scheduler.execute_evaluation(trace_id="trace-eval-2")
    assert result2 is None  # Skipped due to lock

    # 3. Allow Evaluation 1 to complete
    eval_can_finish.set()
    result1 = await task1

    assert result1 is not None
    assert result1.success is True
    assert result1.trace_id == "trace-eval-1"
    assert scheduler.evaluation_count == 1


# ==============================================================================
# 4. Error Isolation & Failure Recovery Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_evaluation_failure_does_not_crash_scheduler():
    """
    Verify that an upstream failure is caught, logged in ObservationResult,
    and does not terminate the background scheduler loop.
    """
    call_count = 0

    async def flapping_orchestrate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise AggregationError("Traffic Intelligence", "Connection refused to :8001")
        return make_mock_decision()

    mock_aggregator = MagicMock(spec=ContextAggregatorService)
    mock_aggregator.orchestrate_decision = AsyncMock(side_effect=flapping_orchestrate)

    scheduler = ObservationSchedulerService(
        aggregator=mock_aggregator,
        interval_seconds=0.05,
    )

    # 1. Execute failing cycle
    res1 = await scheduler.execute_evaluation()
    assert res1.success is False
    assert "[Traffic Intelligence] Connection refused" in res1.error
    assert scheduler.failure_count == 1
    assert scheduler.evaluation_count == 0

    # 2. Execute subsequent healthy cycle
    res2 = await scheduler.execute_evaluation()
    assert res2.success is True
    assert res2.scaling_decision.action == ScalingAction.HOLD
    assert scheduler.evaluation_count == 1


# ==============================================================================
# 5. Trace ID & Metadata Generation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_scheduler_generates_unique_trace_id_per_evaluation():
    """Verify that every scheduled evaluation receives a unique trace_id."""
    captured_traces = []

    async def mock_orchestrate(*args, **kwargs):
        captured_traces.append(kwargs.get("trace_id"))
        return make_mock_decision(trace_id=kwargs.get("trace_id"))

    mock_aggregator = MagicMock(spec=ContextAggregatorService)
    mock_aggregator.orchestrate_decision = AsyncMock(side_effect=mock_orchestrate)

    scheduler = ObservationSchedulerService(
        aggregator=mock_aggregator,
        interval_seconds=0.05,
    )

    res1 = await scheduler.execute_evaluation()
    res2 = await scheduler.execute_evaluation()

    assert res1.trace_id.startswith("trace-sched-")
    assert res2.trace_id.startswith("trace-sched-")
    assert res1.trace_id != res2.trace_id
    assert captured_traces[0] == res1.trace_id
    assert captured_traces[1] == res2.trace_id


# ==============================================================================
# 6. Timeout / Hang Protection Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_scheduler_evaluation_timeout_protection():
    """Verify that a hanging evaluation is aborted after evaluation_timeout_seconds."""
    async def hanging_orchestrate(*args, **kwargs):
        await asyncio.sleep(2.0)
        return make_mock_decision()

    mock_aggregator = MagicMock(spec=ContextAggregatorService)
    mock_aggregator.orchestrate_decision = AsyncMock(side_effect=hanging_orchestrate)

    scheduler = ObservationSchedulerService(
        aggregator=mock_aggregator,
        interval_seconds=0.05,
        evaluation_timeout_seconds=0.1,  # Short timeout for test
    )

    start = time.perf_counter()
    res = await scheduler.execute_evaluation()
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5
    assert res.success is False
    assert "timed out after 0.1s" in res.error.lower()
    assert scheduler.failure_count == 1


# ==============================================================================
# 7. No Actuation Safety Invariant Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_scheduler_contains_zero_actuation():
    """
    Verify that the scheduler only produces ObservationResult with dry_run=True
    and does not mutate any cluster or replica state.
    """
    mock_aggregator = MagicMock(spec=ContextAggregatorService)
    decision = make_mock_decision(action=ScalingAction.SCALE, recommended_pods=8)
    mock_aggregator.orchestrate_decision = AsyncMock(return_value=decision)

    scheduler = ObservationSchedulerService(aggregator=mock_aggregator)
    res = await scheduler.execute_evaluation()

    assert res.success is True
    assert res.scaling_decision.dry_run is True
    assert res.scaling_decision.shadow_mode is True
    assert res.scaling_decision.recommended_pods == 8

