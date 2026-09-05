"""
SentinelScale — Demand Intelligence — Mock Demand Provider
Deterministic synthetic observation generator for development, testing, and
integration without real telemetry infrastructure.

The mock produces a realistic sinusoidal demand pattern with configurable
baseline RPS and gentle time-of-day variation.
"""
import math
import time
from typing import List

from app.models.demand import DemandObservation
from app.providers.base import DemandProvider


class MockDemandProvider(DemandProvider):
    """
    Generates deterministic synthetic demand observations.

    Demand pattern: sinusoidal oscillation around a baseline RPS, simulating
    realistic time-of-day traffic variation. The same window_seconds always
    produces the same set of observations (deterministic).
    """

    OBSERVATION_INTERVAL_SECONDS = 30  # one reading every 30 seconds
    BASELINE_RPS = 850.0               # steady-state legitimate demand
    AMPLITUDE_RPS = 150.0              # ±150 rps sinusoidal variation
    PERIOD_SECONDS = 3600.0            # 1-hour demand cycle

    def __init__(self, reference_time: float | None = None):
        """
        Args:
            reference_time: Unix epoch to use as "now". If None, uses
                            actual current time. Setting this explicitly
                            makes tests deterministic.
        """
        self._reference_time = reference_time

    @property
    def name(self) -> str:
        return "MockDemandProvider"

    def _now(self) -> float:
        return self._reference_time if self._reference_time is not None else time.time()

    def get_observations(self, window_seconds: int) -> List[DemandObservation]:
        """
        Generate synthetic observations covering the past window_seconds.

        Returns observations at OBSERVATION_INTERVAL_SECONDS cadence,
        oldest first.
        """
        now = self._now()
        start = now - window_seconds

        observations = []
        t = start
        while t <= now:
            # Sinusoidal variation: demand peaks and troughs within each period
            phase = (t % self.PERIOD_SECONDS) / self.PERIOD_SECONDS
            rps = self.BASELINE_RPS + self.AMPLITUDE_RPS * math.sin(2 * math.pi * phase)
            rps = max(0.0, round(rps, 2))
            observations.append(DemandObservation(timestamp=t, rps=rps))
            t += self.OBSERVATION_INTERVAL_SECONDS

        return observations
