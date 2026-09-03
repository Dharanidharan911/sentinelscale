from abc import ABC, abstractmethod
from typing import Optional
from app.models.decision import ScalingDecision


class MetricsCollector(ABC):
    """
    Abstract interface for SentinelScale operational metrics collection and exposition.
    """

    @abstractmethod
    def record_observation_success(self, decision: ScalingDecision, duration_s: float) -> None:
        """Record successful observation, decision indicators, HPA divergence, and latency."""
        pass

    @abstractmethod
    def record_observation_failure(self, service: str, error_type: str, duration_s: float) -> None:
        """Record failed observation cycle, upstream failure taxonomy, and duration."""
        pass

    @abstractmethod
    def set_scheduler_running(self, running: bool) -> None:
        """Update scheduler running state gauge."""
        pass

    @abstractmethod
    def record_scheduler_skipped(self) -> None:
        """Increment single-flight skipped observation counter."""
        pass

    @abstractmethod
    def record_history_write(self, success: bool) -> None:
        """Record outcome of decision history persistence write."""
        pass

    @abstractmethod
    def record_history_cleanup(self, count: int) -> None:
        """Record count of historical records deleted by retention policy."""
        pass

    @abstractmethod
    def export_prometheus_text(self) -> str:
        """Export metrics formatted according to Prometheus text exposition format (v0.0.4)."""
        pass

