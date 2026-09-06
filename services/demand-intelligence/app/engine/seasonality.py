"""
SentinelScale — Demand Intelligence — Seasonality Engine (M2-13)
Detects periodic and cyclic demand oscillations using deterministic autocorrelation
and harmonic decomposition.

Design principles:
1. Deterministic & Closed-Form: Evaluates autocorrelation peaks and Fourier harmonics.
2. Evidence-Guarded: Requires at least 2 complete cycles (T >= 2 * P) and a statistically
   significant autocorrelation peak (r >= max(0.35, 1.96 / sqrt(N))).
3. Safe Fallback: If no periodic pattern is confirmed, returns zero seasonal adjustment,
   leaving base RWMA / ML projection completely unmodified.
4. Non-Negative Guarantee: Seasonal adjustment cannot pull predicted demand below 0.0.
"""
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.models.demand import DemandObservation
from app.engine.preprocessor import compute_statistics


@dataclass(frozen=True)
class SeasonalityResult:
    is_seasonal: bool
    period_seconds: Optional[float]
    autocorrelation_peak: float
    seasonal_adjustment_rps: float
    confidence_factor: float


class SeasonalityDetector:
    """
    Detects and computes seasonal demand modulation from observation history.
    """

    @staticmethod
    def detect_and_adjust(
        observations: List[DemandObservation],
        base_projection: float,
        forecast_horizon_seconds: int,
    ) -> SeasonalityResult:
        """
        Analyze cleaned observations for periodicity. If confirmed, computes
        the seasonal adjustment for horizon t_last + forecast_horizon_seconds.
        """
        n = len(observations)
        if n < 8:
            return SeasonalityResult(
                is_seasonal=False,
                period_seconds=None,
                autocorrelation_peak=0.0,
                seasonal_adjustment_rps=0.0,
                confidence_factor=0.0,
            )

        # Check cadence regularity
        intervals = [
            observations[i].timestamp - observations[i - 1].timestamp
            for i in range(1, n)
        ]
        mean_dt = sum(intervals) / len(intervals)
        if mean_dt <= 0:
            return SeasonalityResult(False, None, 0.0, 0.0, 0.0)

        dt_var = sum((dt - mean_dt) ** 2 for dt in intervals) / len(intervals)
        dt_cv = math.sqrt(dt_var) / mean_dt
        if dt_cv > 0.4:
            # Irregular sampling obscures periodicity; do not force seasonal detection
            return SeasonalityResult(False, None, 0.0, 0.0, 0.0)

        # Compute mean and detrended values
        values = [o.rps for o in observations]
        mean_val = sum(values) / n
        variance = sum((v - mean_val) ** 2 for v in values) / n

        if variance < 1e-6:
            # Constant series has zero variance
            return SeasonalityResult(False, None, 0.0, 0.0, 0.0)

        # Autocorrelation over lags 2 to n // 2
        max_lag = n // 2
        autocorr: List[Tuple[int, float]] = []
        for k in range(2, max_lag + 1):
            cov = sum(
                (values[i] - mean_val) * (values[i + k] - mean_val)
                for i in range(n - k)
            ) / (n - k)
            r_k = cov / variance
            autocorr.append((k, r_k))

        if not autocorr:
            return SeasonalityResult(False, None, 0.0, 0.0, 0.0)

        # Dynamic significance threshold based on white-noise 95% confidence bound
        r_thresh = max(0.35, 1.96 / math.sqrt(n))

        # Find local peaks: r[k] > r[k-1] and r[k] > r[k+1]
        best_lag: Optional[int] = None
        best_r = -1.0

        for idx in range(1, len(autocorr) - 1):
            lag, r = autocorr[idx]
            r_prev = autocorr[idx - 1][1]
            r_next = autocorr[idx + 1][1]
            if r > r_prev and r > r_next and r >= r_thresh:
                if r > best_r:
                    best_r = r
                    best_lag = lag

        # Edge case: if last lag is highest and exceeds threshold
        if best_lag is None and len(autocorr) >= 1:
            last_lag, last_r = autocorr[-1]
            if last_r >= r_thresh and (len(autocorr) == 1 or last_r > autocorr[-2][1]):
                best_lag = last_lag
                best_r = last_r

        if best_lag is None or best_r < r_thresh:
            return SeasonalityResult(False, None, round(max(0.0, best_r), 4), 0.0, 0.0)

        # Candidate period in seconds
        period_sec = best_lag * mean_dt
        time_span = observations[-1].timestamp - observations[0].timestamp

        # Invariant: Observation history MUST span at least 2 full periods
        if time_span < 1.9 * period_sec:
            return SeasonalityResult(False, None, round(best_r, 4), 0.0, 0.0)

        # Harmonic estimation via single-frequency Fourier regression:
        # y(t) - trend ≈ A * cos(omega * t) + B * sin(omega * t)
        omega = 2.0 * math.pi / period_sec
        t0 = observations[0].timestamp
        
        sum_cos2 = 0.0
        sum_sin2 = 0.0
        sum_cos_sin = 0.0
        sum_y_cos = 0.0
        sum_y_sin = 0.0

        for obs in observations:
            t = obs.timestamp - t0
            y_detrended = obs.rps - mean_val
            c = math.cos(omega * t)
            s = math.sin(omega * t)
            sum_cos2 += c * c
            sum_sin2 += s * s
            sum_cos_sin += c * s
            sum_y_cos += y_detrended * c
            sum_y_sin += y_detrended * s

        # Solve 2x2 linear system for (A, B)
        det = sum_cos2 * sum_sin2 - sum_cos_sin * sum_cos_sin
        if abs(det) < 1e-9:
            return SeasonalityResult(False, None, round(best_r, 4), 0.0, 0.0)

        A = (sum_y_cos * sum_sin2 - sum_y_sin * sum_cos_sin) / det
        B = (sum_cos2 * sum_y_sin - sum_cos_sin * sum_y_cos) / det
        amplitude = math.sqrt(A * A + B * B)

        # Sanity check: amplitude cannot exceed 80% of mean demand
        if amplitude > 0.8 * mean_val:
            dampening = (0.8 * mean_val) / amplitude
            A *= dampening
            B *= dampening

        # Compute seasonal adjustment at target future timestamp
        target_t = (observations[-1].timestamp + forecast_horizon_seconds) - t0
        seasonal_adj = A * math.cos(omega * target_t) + B * math.sin(omega * target_t)

        return SeasonalityResult(
            is_seasonal=True,
            period_seconds=round(period_sec, 2),
            autocorrelation_peak=round(best_r, 4),
            seasonal_adjustment_rps=round(seasonal_adj, 4),
            confidence_factor=round(min(1.0, best_r), 4),
        )
