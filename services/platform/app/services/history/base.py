from abc import ABC, abstractmethod
from typing import List, Optional
from app.models.history import HistoryStats, StoredObservation


class DecisionHistoryStore(ABC):
    """
    Abstract Base Class defining the persistence contract for SentinelScale
    decision history, audit trails, and historical observation queries.
    """

    @abstractmethod
    def record_observation(self, observation: StoredObservation) -> str:
        """
        Persist a single observation record (successful or failed).
        Returns the observation ID.
        """
        pass

    @abstractmethod
    def get_observation(self, observation_id: str) -> Optional[StoredObservation]:
        """
        Retrieve a single observation by its unique UUID.
        """
        pass

    @abstractmethod
    def get_by_trace_id(self, trace_id: str) -> List[StoredObservation]:
        """
        Retrieve all observation records correlating to a distributed trace_id.
        """
        pass

    @abstractmethod
    def list_observations(
        self,
        limit: int = 50,
        offset: int = 0,
        success: Optional[bool] = None,
        action: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> List[StoredObservation]:
        """
        List observations ordered newest-first with optional filtering and pagination.
        """
        pass

    @abstractmethod
    def cleanup_old_observations(self, retention_days: int) -> int:
        """
        Delete records older than retention_days. Returns the count of deleted records.
        """
        pass

    @abstractmethod
    def get_stats(self, retention_days: int = 7) -> HistoryStats:
        """
        Return summary statistics of the history store.
        """
        pass

