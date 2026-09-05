from typing import Optional
from app.config.settings import settings
from app.services.history.base import DecisionHistoryStore
from app.services.history.demand_accumulator import DemandObservationAccumulator
from app.services.history.sqlite_store import SQLiteDecisionHistoryStore

_global_store: Optional[DecisionHistoryStore] = None
_global_accumulator: Optional[DemandObservationAccumulator] = None


def get_history_store(db_path: Optional[str] = None) -> DecisionHistoryStore:
    """
    Factory function returning the singleton DecisionHistoryStore instance.
    """
    global _global_store
    if _global_store is None or db_path is not None:
        store = SQLiteDecisionHistoryStore(db_path=db_path)
        if db_path is None:
            _global_store = store
        return store
    return _global_store


def get_demand_accumulator(db_path: Optional[str] = None) -> DemandObservationAccumulator:
    """
    Factory function returning the singleton DemandObservationAccumulator instance.
    """
    global _global_accumulator
    if _global_accumulator is None or db_path is not None:
        accumulator = DemandObservationAccumulator(db_path=db_path)
        if db_path is None:
            _global_accumulator = accumulator
        return accumulator
    return _global_accumulator
