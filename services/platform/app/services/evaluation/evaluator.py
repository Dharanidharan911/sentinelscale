import uuid
from datetime import datetime, timezone
from typing import Optional

from app.models.context import DecisionContext
from app.models.decision import ScalingDecision
from app.models.evaluation import (
    EvaluationCategory,
    EvaluationMetrics,
    EvaluationResult,
    RecommendationDifference,
)
from app.services.decision_engine import DecisionEngine
from app.services.evaluation.base import HPAEvaluationService
from app.services.history.base import DecisionHistoryStore


class DefaultHPAEvaluationService(HPAEvaluationService):
    """
    Deterministic implementation of HPA vs. SentinelScale comparative evaluation.
    Evaluates decisions either in-flight from DecisionContext, from a completed
    ScalingDecision, or from a persisted observation record.
    """

    def __init__(
        self,
        decision_engine: Optional[DecisionEngine] = None,
        history_store: Optional[DecisionHistoryStore] = None,
    ):
        self.decision_engine = decision_engine or DecisionEngine()
        self.history_store = history_store

    async def evaluate_context(self, context: DecisionContext) -> EvaluationResult:
        """
        Evaluate a complete DecisionContext and produce a formal comparative EvaluationResult.
        """
        decision = await self.decision_engine.evaluate_decision(context)
        return self.evaluate_decision(decision)

    def evaluate_decision(self, decision: ScalingDecision) -> EvaluationResult:
        """
        Produce a formal comparative EvaluationResult from an existing ScalingDecision.
        """
        hpa_pods = decision.baseline_hpa_recommended_pods
        sentinel_pods = decision.recommended_pods
        current_pods = decision.current_pods
        traffic_risk = decision.traffic_risk
        predicted_legitimate = decision.predicted_legitimate_rps
        current_capacity = decision.current_capacity_rps
        confidence = decision.confidence

        replica_delta = sentinel_pods - hpa_pods
        absolute_replica_delta = abs(replica_delta)
        pod_hours_saved = max(0.0, float(hpa_pods - sentinel_pods))

        capacity_satisfied = predicted_legitimate <= current_capacity

        # Unnecessary scale-up signal: HPA scales up due to traffic while risk is elevated and demand fits capacity
        unnecessary_scale_up = (
            hpa_pods > sentinel_pods
            and traffic_risk >= 0.70
            and capacity_satisfied
        )

        suppression_reason: Optional[str] = None
        if unnecessary_scale_up:
            suppression_reason = (
                f"High traffic risk ({traffic_risk:.2f}) with legitimate demand ({predicted_legitimate:.1f} RPS) "
                f"within capacity ({current_capacity:.1f} RPS). Suppressed overprovisioning of {hpa_pods - sentinel_pods} pods."
            )

        # Recommendation Difference Direction
        if sentinel_pods == hpa_pods:
            diff_direction = RecommendationDifference.EQUAL
        elif sentinel_pods < hpa_pods:
            diff_direction = RecommendationDifference.SENTINELSCALE_FEWER_PODS
        else:
            diff_direction = RecommendationDifference.SENTINELSCALE_MORE_PODS

        # Category and Explanation Determination
        if confidence < 0.50:
            category = EvaluationCategory.UNCERTAIN
            explanation = (
                f"Low composite confidence ({confidence:.2f} < 0.50). "
                f"Comparative evaluation is marked uncertain due to degraded telemetry or forecast inputs."
            )
        elif unnecessary_scale_up:
            category = EvaluationCategory.SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE
            explanation = (
                f"Traditional HPA reactively scaled up to {hpa_pods} pods due to attack/unclassified traffic. "
                f"SentinelScale identified legitimate demand ({predicted_legitimate:.1f} RPS <= {current_capacity:.1f} RPS capacity) "
                f"and suppressed unnecessary scaling, saving {int(pod_hours_saved)} pod-hours/hr."
            )
        elif predicted_legitimate > current_capacity and sentinel_pods > current_pods:
            category = EvaluationCategory.SENTINELSCALE_PROACTIVELY_SCALES
            explanation = (
                f"Legitimate demand ({predicted_legitimate:.1f} RPS) exceeds current capacity ({current_capacity:.1f} RPS). "
                f"SentinelScale recommends scaling to {sentinel_pods} pods (HPA baseline: {hpa_pods} pods)."
            )
        elif sentinel_pods < current_pods and sentinel_pods < hpa_pods:
            category = EvaluationCategory.SCALE_DOWN_DIFFERENCE
            explanation = (
                f"SentinelScale identified legitimate demand ({predicted_legitimate:.1f} RPS) is significantly below "
                f"capacity and recommends scaling down to {sentinel_pods} pods, whereas HPA maintains {hpa_pods} pods."
            )
        elif sentinel_pods == hpa_pods:
            category = EvaluationCategory.ALIGNED
            explanation = (
                f"SentinelScale and reactive HPA baseline recommendations are aligned at {sentinel_pods} pods."
            )
        elif sentinel_pods > hpa_pods:
            category = EvaluationCategory.SENTINELSCALE_PROACTIVELY_SCALES
            explanation = (
                f"SentinelScale proactively scales to {sentinel_pods} pods based on predicted legitimate demand, "
                f"exceeding reactive HPA baseline of {hpa_pods} pods."
            )
        else:
            # Fallback for fewer pods without high risk trigger (e.g. scale-down or risk between 0.5-0.7)
            category = EvaluationCategory.SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE
            explanation = (
                f"SentinelScale recommended {sentinel_pods} pods vs HPA {hpa_pods} pods, preventing excess replica allocation."
            )

        metrics = EvaluationMetrics(
            replica_delta=replica_delta,
            absolute_replica_delta=absolute_replica_delta,
            estimated_pod_hours_saved_per_hour=pod_hours_saved,
            estimated_cpu_cores_saved=None,
            unnecessary_scale_up_signal=unnecessary_scale_up,
            capacity_satisfied=capacity_satisfied,
            suppression_reason=suppression_reason,
        )

        return EvaluationResult(
            evaluation_id=str(uuid.uuid4()),
            trace_id=decision.trace_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            category=category,
            recommendation_difference=diff_direction,
            explanation=explanation,
            hpa_recommended_pods=hpa_pods,
            sentinelscale_recommended_pods=sentinel_pods,
            current_pods=current_pods,
            traffic_risk=traffic_risk,
            predicted_legitimate_rps=predicted_legitimate,
            current_capacity_rps=current_capacity,
            confidence=confidence,
            metrics=metrics,
            dry_run=True,
            shadow_mode=True,
        )

    def evaluate_observation_id(self, observation_id: str) -> EvaluationResult:
        """
        Produce a formal comparative EvaluationResult for a stored observation record.
        """
        if not self.history_store:
            raise ValueError("History store is not configured for observation evaluation.")

        obs = self.history_store.get_observation(observation_id)
        if not obs:
            raise ValueError(f"Observation ID '{observation_id}' not found.")

        if not obs.success or obs.recommended_pods is None or obs.baseline_hpa_recommended_pods is None:
            raise ValueError(f"Observation ID '{observation_id}' does not contain valid decision telemetry.")

        decision = ScalingDecision(
            decision_id=obs.id,
            event_id="evt-replay",
            trace_id=obs.trace_id,
            timestamp=obs.timestamp,
            contract_version="1.0.0",
            service_version="1.0.0",
            model_version="1.0.0",
            action=obs.action or "HOLD",
            reason=obs.reason or "Historical replay evaluation.",
            confidence=obs.confidence if obs.confidence is not None else 1.0,
            traffic_risk=obs.traffic_risk if obs.traffic_risk is not None else 0.0,
            predicted_legitimate_rps=obs.predicted_legitimate_rps if obs.predicted_legitimate_rps is not None else 0.0,
            current_capacity_rps=obs.current_capacity_rps if obs.current_capacity_rps is not None else 100.0,
            current_pods=obs.current_pods if obs.current_pods is not None else 2,
            recommended_pods=obs.recommended_pods,
            baseline_hpa_recommended_pods=obs.baseline_hpa_recommended_pods,
            pod_delta_vs_baseline=obs.pod_delta_vs_baseline if obs.pod_delta_vs_baseline is not None else (obs.recommended_pods - obs.baseline_hpa_recommended_pods),
            policy=obs.policy or "guardrail",
            dry_run=True,
            shadow_mode=True,
        )
        return self.evaluate_decision(decision)
