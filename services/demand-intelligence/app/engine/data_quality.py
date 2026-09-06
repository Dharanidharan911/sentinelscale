"""
SentinelScale — Demand Intelligence — Data Quality Intelligence (M2-12)
Evaluates observational data quality, completeness, sampling regularity,
staleness, and signal-to-noise ratio.

Design principles:
1. Purely diagnostic and observational: DOES NOT mutate or scale predicted demand.
2. Deterministic: same observation input always yields identical quality metrics.
3. Quantified metrics: provides continuous [0.0, 1.0] scores and categorical ratings.
4. Robust to edge cases: handles small datasets, single intervals, and zero demand gracefully.
"""
import math
import time
from dataclasses import dataclass
from typing import List, Optional

from app.models.demand import DemandObservation
from app.engine.preprocessor import compute_statistics


@dataclass(frozen=True)
class DataQualityReport:
    """Structured assessment of telemetry observation quality."""
    sample_count: int
    time_span_seconds: float
    cadence_seconds: float
    completeness_ratio: float      # [0.0, 1.0] expected vs observed sample ratio
    cadence_regularity: float      # [0.0, 1.0] 1.0 = perfectly uniform time steps
    staleness_seconds: float       # Elapsed seconds since the most recent observation
    noise_to_signal_ratio: float   # std_dev / mean (or 0.0 if mean is 0)
    quality_score: float           # [0.0, 1.0] composite quality metric
    quality_rating: str            # "EXCELLENT", "GOOD", "DEGRADED", "POOR"


class DataQualityAssessor:
    """
    Evaluates historical observation quality for demand forecasting.
    Feeds into confidence calibration and explainability without altering demand volume.
    """

    @staticmethod
    def assess(
        observations: List[DemandObservation],
        reference_time: Optional[float] = None,
    ) -> DataQualityReport:
        """
        Assess quality of a preprocessed, time-sorted list of DemandObservation.
        """
        n = len(observations)
        if n == 0:
            return DataQualityReport(
                sample_count=0,
                time_span_seconds=0.0,
                cadence_seconds=0.0,
                completeness_ratio=0.0,
                cadence_regularity=0.0,
                staleness_seconds=0.0,
                noise_to_signal_ratio=0.0,
                quality_score=0.0,
                quality_rating="POOR",
            )

        if n == 1:
            ref = reference_time if reference_time is not None else observations[-1].timestamp
            staleness = max(0.0, ref - observations[-1].timestamp)
            return DataQualityReport(
                sample_count=1,
                time_span_seconds=0.0,
                cadence_seconds=0.0,
                completeness_ratio=1.0,
                cadence_regularity=1.0,
                staleness_seconds=round(staleness, 2),
                noise_to_signal_ratio=0.0,
                quality_score=0.25,
                quality_rating="POOR",
            )

        # Compute interval metrics
        intervals = [
            observations[i].timestamp - observations[i - 1].timestamp
            for i in range(1, n)
        ]
        time_span = observations[-1].timestamp - observations[0].timestamp

        # Median interval as robust cadence estimate
        sorted_intervals = sorted(intervals)
        cadence = sorted_intervals[len(sorted_intervals) // 2]
        cadence = max(0.1, cadence)

        # Cadence regularity: 1.0 / (1.0 + CV of intervals)
        mean_interval = sum(intervals) / len(intervals)
        if mean_interval > 0:
            var_interval = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
            cv_interval = math.sqrt(var_interval) / mean_interval
            regularity = 1.0 / (1.0 + cv_interval)
        else:
            regularity = 0.0

        # Completeness ratio: observed count vs theoretical count over time_span
        expected_samples = int(round(time_span / cadence)) + 1 if time_span > 0 else n
        completeness = min(1.0, max(0.0, n / max(1, expected_samples)))

        # Staleness
        ref = reference_time if reference_time is not None else observations[-1].timestamp
        staleness = max(0.0, ref - observations[-1].timestamp)
        # Freshness decays if staleness exceeds 3 cadence intervals
        freshness = math.exp(-max(0.0, staleness - 2 * cadence) / max(cadence, 30.0))

        # Noise to signal ratio
        mean_rps, std_dev_rps, _ = compute_statistics(observations)
        if mean_rps > 0:
            noise_ratio = std_dev_rps / mean_rps
        else:
            noise_ratio = 0.0

        noise_stability = 1.0 / (1.0 + noise_ratio)

        # Composite quality score: geometric mean of dimensions
        composite = (completeness * regularity * freshness * noise_stability) ** (1 / 4)
        # Sample count factor: low N bounds maximum achievable score
        sample_scaling = min(1.0, n / 10.0)
        final_score = round(min(1.0, max(0.0, composite * (0.5 + 0.5 * sample_scaling))), 4)

        # Categorical rating
        if final_score >= 0.80 and n >= 8:
            rating = "EXCELLENT"
        elif final_score >= 0.60 and n >= 5:
            rating = "GOOD"
        elif final_score >= 0.35 and n >= 3:
            rating = "DEGRADED"
        else:
            rating = "POOR"

        return DataQualityReport(
            sample_count=n,
            time_span_seconds=round(time_span, 2),
            cadence_seconds=round(cadence, 2),
            completeness_ratio=round(completeness, 4),
            cadence_regularity=round(regularity, 4),
            staleness_seconds=round(staleness, 2),
            noise_to_signal_ratio=round(noise_ratio, 4),
            quality_score=final_score,
            quality_rating=rating,
        )
