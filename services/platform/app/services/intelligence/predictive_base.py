from abc import ABC, abstractmethod
from typing import Dict, Optional
from app.models.prediction import PredictiveForecast


class PredictiveIntelligenceService(ABC):
    """
    Abstract Service Interface for Adaptive Predictive Intelligence.
    Forecasts short-horizon operational demand, capacity pressure, and advisory replica requirements
    without mutating cluster state or feeding back into the deterministic DecisionEngine.
    """

    @abstractmethod
    def forecast(
        self,
        window: Optional[str] = None,
        horizon: Optional[str] = None,
        horizon_seconds: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        observation_id: Optional[str] = None,
        current_values: Optional[Dict[str, float]] = None,
    ) -> PredictiveForecast:
        """
        Generate short-horizon deterministic forecast and capacity pressure evaluation.
        """
        pass

