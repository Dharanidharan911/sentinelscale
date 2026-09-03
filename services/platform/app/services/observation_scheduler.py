import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from app.config.settings import settings
from app.logging import logger
from app.models.decision import ScalingDecision
from app.models.history import StoredObservation
from app.services.context_aggregator import AggregationError, ContextAggregatorService
from app.services.history.base import DecisionHistoryStore
from app.services.history.factory import get_history_store
from app.services.metrics.base import MetricsCollector
from app.services.metrics.factory import get_metrics_service


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
    Phase 4A/4B/4C Continuous Observation Scheduler, Audit Recorder & Metrics Publisher.
    Periodically triggers end-to-end decision orchestration via ContextAggregatorService,
    persists observation records in DecisionHistoryStore, and updates Prometheus metrics.
    Guarantees:
      - Observation-only (never invokes actuation or infrastructure mutation)
      - Single-flight / non-overlapping execution via asyncio.Lock
      - Unique distributed trace_id per evaluation
      - Error isolation (failures do not crash the scheduler loop)
      - Graceful startup, retention cleanup, and shutdown lifecycle management
    """

    def __init__(
        self,
        aggregator: Optional[ContextAggregatorService] = None,
        history_store: Optional[DecisionHistoryStore] = None,
        metrics: Optional[MetricsCollector] = None,
        interval_seconds: Optional[float] = None,
        target_namespace: Optional[str] = None,
        target_workload: Optional[str] = None,
        window_seconds: Optional[int] = None,
        forecast_horizon_seconds: Optional[int] = None,
        evaluation_timeout_seconds: Optional[float] = None,
    ):
        self.aggregator = aggregator or ContextAggregatorService()
        self.history_store = (
            history_store
            if history_store is not None
            else (get_history_store() if settings.DECISION_HISTORY_ENABLED else None)
        )
        self.metrics = (
            metrics
            if metrics is not None
            else (get_metrics_service() if settings.METRICS_ENABLED else None)
        )
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
        if self.metrics:
            self.metrics.set_scheduler_running(True)

        logger.info(
            f"Starting ObservationScheduler for '{self.target_namespace}/{self.target_workload}' "
            f"(interval: {self.interval_seconds}s, timeout: {self.evaluation_timeout_seconds}s, "
            f"history_enabled: {self.history_store is not None})",
            extra={"service": "platform"},
        )

        # Run retention cleanup on startup if history store is active
        if self.history_store:
            try:
                deleted = self.history_store.cleanup_old_observations(settings.DECISION_HISTORY_RETENTION_DAYS)
                if self.metrics and deleted > 0:
                    self.metrics.record_history_cleanup(deleted)
            except Exception as clean_err:
                logger.warning(
                    f"Initial retention cleanup failed: {clean_err}",
                    extra={"service": "platform"},
                )

        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Gracefully stop the background observation task and await cancellation."""
        if not self._running:
            return

        self._running = False
        if self.metrics:
            self.metrics.set_scheduler_running(False)

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
        Guarantees single-flight non-overlapping execution, audit persistence, and metric publication.
        """
        if self._lock.locked():
            if self.metrics:
                self.metrics.record_scheduler_skipped()
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

                duration_s = time.perf_counter() - start_time
                duration_ms = round(duration_s * 1000, 2)
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

                # Update operational metrics
                if self.metrics:
                    self.metrics.record_observation_success(decision, duration_s)

                # Persist successful observation record
                if self.history_store:
                    try:
                        obs = StoredObservation(
                            id=evaluation_id,
                            trace_id=resolved_trace_id,
                            timestamp=started_at,
                            completed_at=completed_at,
                            duration_ms=duration_ms,
                            success=True,
                            action=decision.action,
                            reason=decision.reason,
                            confidence=decision.confidence,
                            recommended_pods=decision.recommended_pods,
                            current_pods=decision.current_pods,
                            baseline_hpa_recommended_pods=decision.baseline_hpa_recommended_pods,
                            pod_delta_vs_baseline=decision.pod_delta_vs_baseline,
                            traffic_risk=decision.traffic_risk,
                            predicted_legitimate_rps=decision.predicted_legitimate_rps,
                            current_capacity_rps=decision.current_capacity_rps,
                            policy=decision.policy,
                            dry_run=decision.dry_run,
                            shadow_mode=decision.shadow_mode,
                            scaling_decision_json=decision.model_dump_json(),
                        )
                        self.history_store.record_observation(obs)
                        if self.metrics:
                            self.metrics.record_history_write(True)
                    except Exception as hist_err:
                        if self.metrics:
                            self.metrics.record_history_write(False)
                        logger.error(
                            f"Failed to record observation in history store: {hist_err}",
                            extra={"evaluation_id": evaluation_id, "trace_id": resolved_trace_id, "service": "platform"},
                        )

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
                duration_s = time.perf_counter() - start_time
                duration_ms = round(duration_s * 1000, 2)
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

                # Update operational failure metrics
                if self.metrics:
                    source_svc = exc.source if isinstance(exc, AggregationError) else "platform"
                    self.metrics.record_observation_failure(
                        service=source_svc,
                        error_type=error_msg,
                        duration_s=duration_s,
                    )

                # Persist failed observation record for audit & debugging
                if self.history_store:
                    try:
                        obs = StoredObservation(
                            id=evaluation_id,
                            trace_id=resolved_trace_id,
                            timestamp=started_at,
                            completed_at=completed_at,
                            duration_ms=duration_ms,
                            success=False,
                            error_type=exc.__class__.__name__,
                            error_message=error_msg,
                        )
                        self.history_store.record_observation(obs)
                        if self.metrics:
                            self.metrics.record_history_write(True)
                    except Exception as hist_err:
                        if self.metrics:
                            self.metrics.record_history_write(False)
                        logger.error(
                            f"Failed to record observation failure in history store: {hist_err}",
                            extra={"evaluation_id": evaluation_id, "trace_id": resolved_trace_id, "service": "platform"},
                        )

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
