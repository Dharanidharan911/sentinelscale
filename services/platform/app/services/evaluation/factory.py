from typing import Optional
from app.services.decision_engine import DecisionEngine
from app.services.evaluation.base import HPAEvaluationService
from app.services.evaluation.evaluator import DefaultHPAEvaluationService
from app.services.history.base import DecisionHistoryStore
from app.services.history.factory import get_history_store

_evaluation_service_instance: Optional[HPAEvaluationService] = None


def get_evaluation_service(
    decision_engine: Optional[DecisionEngine] = None,
    history_store: Optional[DecisionHistoryStore] = None,
) -> HPAEvaluationService:
    """
    Factory returning singleton HPAEvaluationService instance.
    """
    global _evaluation_service_instance
    if _evaluation_service_instance is None or decision_engine is not None or history_store is not None:
        store = history_store or get_history_store()
        engine = decision_engine or DecisionEngine()
        _evaluation_service_instance = DefaultHPAEvaluationService(
            decision_engine=engine,
            history_store=store,
        )
    return _evaluation_service_instance

