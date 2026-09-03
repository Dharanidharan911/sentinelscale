from dataclasses import dataclass
from enum import Enum
from app.config.settings import settings
from app.pipeline.features import ExtractedTrafficFeatures


class BurstLevel(str, Enum):
    NOMINAL = "nominal"
    ELEVATED = "elevated"
    SPIKE = "spike"
    EXTREME = "extreme"


@dataclass(frozen=True)
class BurstDetectionResult:
    level: BurstLevel
    burst_ratio: float
    is_burst: bool
    signal_tag: str | None


class BurstDetector:
    """Evaluates burst and surge characteristics against baseline rates."""

    @staticmethod
    def detect(features: ExtractedTrafficFeatures) -> BurstDetectionResult:
        ratio = features.burst_ratio

        if ratio >= settings.BURST_RATIO_EXTREME:
            return BurstDetectionResult(
                level=BurstLevel.EXTREME,
                burst_ratio=ratio,
                is_burst=True,
                signal_tag="extreme_burst_rate"
            )
        elif ratio >= settings.BURST_RATIO_SPIKE:
            return BurstDetectionResult(
                level=BurstLevel.SPIKE,
                burst_ratio=ratio,
                is_burst=True,
                signal_tag="high_burst_rate"
            )
        elif ratio >= settings.BURST_RATIO_ELEVATED:
            return BurstDetectionResult(
                level=BurstLevel.ELEVATED,
                burst_ratio=ratio,
                is_burst=True,
                signal_tag="elevated_traffic_burst"
            )
        else:
            return BurstDetectionResult(
                level=BurstLevel.NOMINAL,
                burst_ratio=ratio,
                is_burst=False,
                signal_tag=None
            )

