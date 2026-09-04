from abc import ABC, abstractmethod
from typing import Optional
from app.models.intelligence import HistoricalDivergence, HistoricalSummary, HistoricalTrends


class HistoricalIntelligenceService(ABC):
    """
    Abstract Service Interface for Historical Intelligence.
    Consumes durable decision history and provides deterministic analytical
    operations, trend aggregation, and baseline HPA divergence breakdown.
    """

    @abstractmethod
    def get_summary(
        self,
        window: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> HistoricalSummary:
        """
        Generate aggregated historical summary of observation counts, demand,
        traffic risk, capacity, pod recommendations, and decision quality.
        """
        pass

    @abstractmethod
    def get_trends(
        self,
        window: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        bucket_seconds: Optional[int] = None,
    ) -> HistoricalTrends:
        """
        Generate time-bucketed historical trends across the requested time range.
        """
        pass

    @abstractmethod
    def get_divergence(
        self,
        window: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> HistoricalDivergence:
        """
        Generate detailed comparative analysis between SentinelScale recommendations
        and standard reactive HPA baseline recommendations.
        """
        pass

