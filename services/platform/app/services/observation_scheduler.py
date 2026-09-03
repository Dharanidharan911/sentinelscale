import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from app.config.settings import settings
from app.logging import logger
from app.models.decision import ScalingDecision
from app.services.context_aggregator import ContextAggregatorService


@dataclass
class ObservationResult:
    """Internal representation of a single scheduled observation evaluation cycle."""
    evaluation_id: str
    trace_id: str
    started_at: str
    completed_at: str
    duration_ms: float
    success: bool
    scaling_decision: Optional[ScalingDecision] = None
    error: Optional[str] = None


class ObservationSchedulerService:
    """
    Phase 4A Continuous Observation Scheduler.
    Periodically triggers end-to-end decision orchestration via ContextAggregatorService.
    Guarantees:
      - Observation-only (never invokes actuation or infrastructure mutation)
      - Single-flight / non-overlapping execution via asyncio.Lock
      - Unique distributed trace_id per evaluation
      - Error isolation (failures log cleanly and do not crash the scheduler loop)
      - Graceful startup and shutdown lifecycle management
    """

    def __init__(
        self,
        aggregator: Optional[ContextAggregatorService] = None,
        interval_seconds: Optional[float] = None,
        target_namespace: Optional[str] = None,
        target_workload: Optional[str] = None,
        window_seconds: Optional[int] = None,
        forecast_horizon_seconds: Optional[int] = None,
        evaluation_timeout_seconds: Optional[float] = None,
    ):
        self.aggregator = aggregator or ContextAggregatorService()
        self.interval_seconds = interval_seconds or settings.OBSERVATION_INTERVAL_SECONDS
        self.target_namespace = target_namespace or settings.OBSERVATION_TARGET_NAMESPACE
        self.target_workload = target_workload or settings.OBSERVATION_TARGET_WORKLOAD
        self.window_seconds = window_seconds or settings.OBSERVATION_WINDOW_SECONDS
        self.forecast_horizon_seconds = forecast_horizon_seconds or settings.OBSERVATION_FORECAST_HORIZON_SECONDS
        self.evaluation_timeout_seconds = evaluation_timeout_seconds or settings.OBSERVATION_EVALUATION_TIMEOUT_SECONDS

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._last_result: Optional[ObservationResult] = None
        self._evaluation_count = 0
        self._failure_count = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_result(self) -> Optional[ObservationResult]:
        return self._last_result

    @property
    def evaluation_count(self) -> int:
        return self._evaluation_count

    @property
    def failure_count(self) -> int:
        return self._failure_count

    async def start(self) -> None:
        """Start the continuous observation background task if not already running."""
        if self._running:
            return

        self._running = True
        logger.info(
            f"Starting ObservationScheduler for '{self.target_namespace}/{self.target_workload}' "
            f"(interval: {self.interval_seconds}s, timeout: {self.evaluation_timeout_seconds}s)",
            extra={"service": "platform"},
        )
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Gracefully stop the background observation task and await cancellation."""
        if not self._running:
            return

        self._running = False
        logger.info("Stopping ObservationScheduler...", extra={"service": "platform"})

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("ObservationScheduler stopped cleanly.", extra={"service": "platform"})

    async def execute_evaluation(self, trace_id: Optional[str] = None) -> Optional[ObservationResult]:
        """
        Execute a single scheduled observation evaluation cycle.
        Guarantees single-flight non-overlapping execution. If an evaluation is already
        in progress, subsequent triggers are skipped safely until the next cycle.
        """
        if self._lock.locked():
            logger.warning(
                f"Skipping scheduled observation: previous evaluation is still in progress.",
                extra={"service": "platform"},
            )
            return None

        async with self._lock:
            resolved_trace_id = trace_id or f"trace-sched-{uuid.uuid4().hex[:12]}"
            evaluation_id = str(uuid.uuid4())
            started_at = datetime.now(timezone.utc).isoformat()
            start_time = time.perf_counter()

            try:
                # Execute orchestration protected by evaluation-level timeout
                decision = await asyncio.wait_for(
                    self.aggregator.orchestrate_decision(
                        namespace=self.target_namespace,
                        workload=self.target_workload,
                        window_seconds=self.window_seconds,
                        forecast_horizon_seconds=self.forecast_horizon_seconds,
                        trace_id=resolved_trace_id,
                    ),
                    timeout=self.evaluation_timeout_seconds,
                )

                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                completed_at = datetime.now(timezone.utc).isoformat()

                result = ObservationResult(
                    evaluation_id=evaluation_id,
                    trace_id=resolved_trace_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    success=True,
                    scaling_decision=decision,
                )

                self._last_result = result
                self._evaluation_count += 1

                logger.info(
                    f"Observation #{self._evaluation_count} completed: Action={decision.action.value}, "
                    f"RecommendedPods={decision.recommended_pods}, BaselineHPAPods={decision.baseline_hpa_recommended_pods}, "
                    f"PodDelta={decision.pod_delta_vs_baseline} in {duration_ms}ms",
                    extra={
                        "evaluation_id": evaluation_id,
                        "trace_id": resolved_trace_id,
                        "action": decision.action.value,
                        "duration_ms": duration_ms,
                        "service": "platform",
                    },
                )
                return result

            except asyncio.CancelledError:
                # Propagate task cancellation cleanly on shutdown
                raise
            except Exception as exc:
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                completed_at = datetime.now(timezone.utc).isoformat()
                error_msg = (
                    f"Evaluation timed out after {self.evaluation_timeout_seconds}s"
                    if isinstance(exc, asyncio.TimeoutError)
                    else str(exc)
                )

                result = ObservationResult(
                    evaluation_id=evaluation_id,
                    trace_id=resolved_trace_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    success=False,
                    error=error_msg,
                )

                self._last_result = result
                self._failure_count += 1

                logger.error(
                    f"Observation cycle failed in {duration_ms}ms: {error_msg}",
                    extra={
                        "evaluation_id": evaluation_id,
                        "trace_id": resolved_trace_id,
                        "duration_ms": duration_ms,
                        "error": error_msg,
                        "service": "platform",
                    },
                )
                return result

    async def _run_loop(self) -> None:
        """Periodic background evaluation loop."""
        try:
            while self._running:
                await self.execute_evaluation()
                try:
                    await asyncio.sleep(self.interval_seconds)
                except asyncio.CancelledError:
                    break
        except asyncio.CancelledError:
            pass


# Global singleton instance for application lifespan integration
_global_scheduler: Optional[ObservationSchedulerService] = None


def get_observation_scheduler() -> ObservationSchedulerService:
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = ObservationSchedulerService()
    return _global_scheduler

