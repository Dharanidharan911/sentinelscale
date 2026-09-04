from abc import ABC, abstractmethod
from typing import Optional
from app.models.context import DecisionContext
from app.models.decision import ScalingDecision
from app.models.evaluation import EvaluationResult


class HPAEvaluationService(ABC):
    """
    Abstract Base Class defining the contract for HPA vs. SentinelScale formal evaluation.
    """

    @abstractmethod
    async def evaluate_context(self, context: DecisionContext) -> EvaluationResult:
        """
        Evaluate a complete DecisionContext and produce a formal comparative EvaluationResult.
        """
        pass

    @abstractmethod
    def evaluate_decision(self, decision: ScalingDecision) -> EvaluationResult:
        """
        Produce a formal comparative EvaluationResult from an existing ScalingDecision.
        """
        pass

    @abstractmethod
    def evaluate_observation_id(self, observation_id: str) -> EvaluationResult:
        """
        Produce a formal comparative EvaluationResult for a stored observation record.
        """
        pass

