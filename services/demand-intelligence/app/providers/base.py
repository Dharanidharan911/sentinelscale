"""
SentinelScale — Demand Intelligence — Provider Abstraction
Abstract interface for demand data providers.

Architecture principle: forecasting logic never directly queries Prometheus,
Kubernetes, or any external telemetry system. Providers supply observations;
the forecasting engine consumes observations.
"""
from abc import ABC, abstractmethod
from typing import List

from app.models.demand import DemandObservation


class DemandProvider(ABC):
    """
    Abstract base for all demand data sources.
    Implementations provide a time-ordered list of DemandObservation objects
    covering the requested historical window.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name for logging and error messages."""
        ...

    @abstractmethod
    def get_observations(self, window_seconds: int) -> List[DemandObservation]:
        """
        Return demand observations covering the past `window_seconds`.

        Args:
            window_seconds: How many seconds of history to return.

        Returns:
            List of DemandObservation objects, ordered oldest-first.
            May be empty if no data is available — callers must handle this.

        Raises:
            ProviderUnavailableError: If the provider cannot be reached at all.
        """
        ...
