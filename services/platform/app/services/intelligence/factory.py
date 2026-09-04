from typing import Optional
from app.services.history.base import DecisionHistoryStore
from app.services.history.factory import get_history_store
from app.services.intelligence.anomaly import AnomalyIntelligenceService
from app.services.intelligence.base import HistoricalIntelligenceService
from app.services.intelligence.baseline import BehavioralBaselineService
from app.services.intelligence.historical import DefaultHistoricalIntelligenceService
from app.services.intelligence.predictive import DefaultPredictiveIntelligenceService
from app.services.intelligence.predictive_base import PredictiveIntelligenceService

_intelligence_service_instance: Optional[HistoricalIntelligenceService] = None
_anomaly_service_instance: Optional[AnomalyIntelligenceService] = None
_predictive_service_instance: Optional[PredictiveIntelligenceService] = None


def get_historical_intelligence_service(
    history_store: Optional[DecisionHistoryStore] = None,
) -> HistoricalIntelligenceService:
    """
    Factory returning singleton HistoricalIntelligenceService backed by DecisionHistoryStore.
    """
    global _intelligence_service_instance
    if _intelligence_service_instance is None or history_store is not None:
        store = history_store or get_history_store()
        _intelligence_service_instance = DefaultHistoricalIntelligenceService(history_store=store)
    return _intelligence_service_instance


def get_anomaly_intelligence_service(
    history_store: Optional[DecisionHistoryStore] = None,
    baseline_service: Optional[BehavioralBaselineService] = None,
) -> AnomalyIntelligenceService:
    """
    Factory returning singleton AnomalyIntelligenceService.
    """
    global _anomaly_service_instance
    if _anomaly_service_instance is None or history_store is not None:
        store = history_store or get_history_store()
        _anomaly_service_instance = AnomalyIntelligenceService(
            history_store=store,
            baseline_service=baseline_service,
        )
    return _anomaly_service_instance


def get_predictive_intelligence_service(
    history_store: Optional[DecisionHistoryStore] = None,
) -> PredictiveIntelligenceService:
    """
    Factory returning singleton PredictiveIntelligenceService.
    """
    global _predictive_service_instance
    if _predictive_service_instance is None or history_store is not None:
        store = history_store or get_history_store()
        _predictive_service_instance = DefaultPredictiveIntelligenceService(history_store=store)
    return _predictive_service_instance
