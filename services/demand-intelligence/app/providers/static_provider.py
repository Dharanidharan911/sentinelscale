"""
SentinelScale — Demand Intelligence — Static Observation Provider
Wraps a pre-supplied list of observations as a DemandProvider.

Used when the API caller (e.g. Member 3 adapter, integration tests) passes
observations directly in the request body, bypassing any telemetry provider.
"""
from typing import List

from app.models.demand import DemandObservation
from app.providers.base import DemandProvider


class StaticObservationProvider(DemandProvider):
    """
    Returns a fixed, caller-supplied list of observations.
    No external I/O — deterministic and suitable for testing.
    """

    def __init__(self, observations: List[DemandObservation]):
        self._observations = observations

    @property
    def name(self) -> str:
        return "StaticObservationProvider"

    def get_observations(self, window_seconds: int) -> List[DemandObservation]:
        """
        Return the supplied observations as-is.
        window_seconds is ignored — the caller already filtered to the
        desired window before constructing this provider.
        """
        return list(self._observations)
