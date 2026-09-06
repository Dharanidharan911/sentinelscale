"""
SentinelScale — Demand Intelligence — Forecast Explainability Engine (M2-14)
Synthesizes deterministic, human-readable and machine-parseable explanation
tags describing why a forecast took its value.

Design principles:
1. Purely observational & additive: DOES NOT alter the frozen JSON schema
   contracts/demand/demand_forecast.schema.json v1.0.0.
2. Deterministic: identically preprocessed data yields identical explanation tags.
3. Multi-dimensional: covers trend direction, volatility, data quality, seasonality,
   uncertainty interval width, and model execution path.
"""
from dataclasses import dataclass
from typing import List, Optional

from app.models.demand import DemandForecast, DemandObservation
from app.engine.preprocessor import compute_statistics
from app.engine.data_quality import DataQualityAssessor
from app.engine.seasonality import SeasonalityDetector


@dataclass(frozen=True)
class ForecastExplanation:
    trend_tag: str
    volatility_tag: str
    quality_tag: str
    seasonality_tag: str
    uncertainty_tag: str
    model_tag: str
    all_tags: List[str]
    summary_text: str

    def to_header_value(self) -> str:
        """Convert tags to comma-separated HTTP header value."""
        return ",".join(self.all_tags)


class ForecastExplainer:
    """
    Generates structured explanation tags from observations and forecast.
    """

    @staticmethod
    def explain(
        forecast: DemandForecast,
        observations: List[DemandObservation],
    ) -> ForecastExplanation:
        """
        Generate comprehensive explanation for a DemandForecast.
        """
        tags: List[str] = []

        # 1. Model Tag
        if "ml" in forecast.model_version.lower():
            model_tag = "MODEL_ML_RIDGE"
        else:
            model_tag = "MODEL_BASELINE_RWMA"
        tags.append(model_tag)

        # 2. Data Quality Tag
        quality = DataQualityAssessor.assess(observations)
        quality_tag = f"QUALITY_{quality.quality_rating}"
        tags.append(quality_tag)

        # 3. Trend Tag
        if len(observations) >= 2:
            mean_rps, std_dev_rps, slope = compute_statistics(observations)
            time_span = observations[-1].timestamp - observations[0].timestamp
            total_change = slope * time_span
            threshold = 0.05 * max(mean_rps, 1.0)  # 5% change over window

            if total_change > threshold:
                trend_tag = "TREND_RISING"
            elif total_change < -threshold:
                trend_tag = "TREND_FALLING"
            else:
                trend_tag = "TREND_STABLE"

            # 4. Volatility Tag
            if mean_rps > 0:
                cv = std_dev_rps / mean_rps
                if cv > 0.6:
                    volatility_tag = "VOLATILITY_HIGH"
                elif cv > 0.2:
                    volatility_tag = "VOLATILITY_MODERATE"
                else:
                    volatility_tag = "VOLATILITY_LOW"
            else:
                volatility_tag = "VOLATILITY_LOW"
        else:
            trend_tag = "TREND_INSUFFICIENT_HISTORY"
            volatility_tag = "VOLATILITY_UNKNOWN"

        tags.append(trend_tag)
        tags.append(volatility_tag)

        # 5. Seasonality Tag
        if len(observations) >= 8:
            seasonality = SeasonalityDetector.detect_and_adjust(
                observations,
                forecast.predicted_legitimate_rps,
                forecast.forecast_horizon_seconds,
            )
            if seasonality.is_seasonal:
                seasonality_tag = f"SEASONALITY_PERIOD_{int(round(seasonality.period_seconds or 0))}S"
            else:
                seasonality_tag = "NO_SEASONALITY_DETECTED"
        else:
            seasonality_tag = "NO_SEASONALITY_DETECTED"
        tags.append(seasonality_tag)

        # 6. Uncertainty Interval Tag
        width = forecast.upper_bound_rps - forecast.lower_bound_rps
        rel_width = width / max(forecast.predicted_legitimate_rps, 1.0)
        if rel_width > 1.0:
            uncertainty_tag = "UNCERTAINTY_WIDE"
        elif rel_width > 0.3:
            uncertainty_tag = "UNCERTAINTY_MODERATE"
        else:
            uncertainty_tag = "UNCERTAINTY_NARROW"
        tags.append(uncertainty_tag)

        summary = (
            f"Forecast {forecast.predicted_legitimate_rps:.2f} RPS over {forecast.forecast_horizon_seconds}s "
            f"via {model_tag}: {trend_tag}, {volatility_tag}, {quality_tag}, {uncertainty_tag}."
        )

        return ForecastExplanation(
            trend_tag=trend_tag,
            volatility_tag=volatility_tag,
            quality_tag=quality_tag,
            seasonality_tag=seasonality_tag,
            uncertainty_tag=uncertainty_tag,
            model_tag=model_tag,
            all_tags=tags,
            summary_text=summary,
        )
