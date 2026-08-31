import math
import uuid
from datetime import datetime, timezone
from app.config.settings import settings
from app.models.context import DecisionContext
from app.models.decision import ScalingAction, ScalingDecision
from app.services.baseline_hpa import BaselineHPACalculator
from app.services.policy_guardrail import PolicyGuardrail


class DecisionEngine:
    """
    Deterministic Decision Engine combining Traffic Intelligence,
    Demand Intelligence, and Resource State.

    Compares security-aware capacity planning against traditional reactive HPA baseline.
    Operates strictly in dry-run / shadow mode for MVP.
    """

    def __init__(self):
        self.baseline_calculator = BaselineHPACalculator()
        self.policy_guardrail = PolicyGuardrail()

    async def evaluate_decision(self, context: DecisionContext) -> ScalingDecision:
        traffic = context.traffic_assessment
        demand = context.demand_forecast
        resources = context.resource_state

        overrides = context.policy_overrides
        pod_capacity = overrides.pod_rps_capacity if overrides and overrides.pod_rps_capacity else settings.DEFAULT_POD_RPS_CAPACITY

        current_pods = max(1, resources.running_pods)
        current_capacity = resources.current_capacity_rps or (current_pods * pod_capacity)
        predicted_legitimate = demand.predicted_legitimate_rps

        # 1. Calculate Baseline Reactive HPA recommendation (blind to traffic classification)
        baseline_hpa_pods = self.baseline_calculator.calculate_baseline_replicas(
            resource_state=resources,
            target_cpu=overrides.target_cpu_utilization if overrides else None
        )

        # 2. Calculate SentinelScale Security-Aware Required Pods
        raw_sentinel_pods = math.ceil(predicted_legitimate / pod_capacity)

        # 3. Apply Policy Guardrails
        recommended_pods, guardrail_reason = self.policy_guardrail.apply_guardrails(
            raw_recommended_pods=raw_sentinel_pods,
            context=context
        )

        # 4. Determine Action & Detailed Rationale
        if traffic.risk_score >= 0.70 and predicted_legitimate <= current_capacity:
            if traffic.classification.value in ["suspicious", "malicious"]:
                action = ScalingAction.HOLD
                reason = (
                    f"High security risk ({traffic.risk_score:.2f}) detected with {traffic.classification.value} traffic. "
                    f"Predicted legitimate demand ({predicted_legitimate:.1f} RPS) is within current capacity ({current_capacity:.1f} RPS). "
                    f"Prevented reactive overprovisioning of {max(0, baseline_hpa_pods - recommended_pods)} pods."
                )
            else:
                action = ScalingAction.HOLD
                reason = f"Legitimate demand ({predicted_legitimate:.1f} RPS) is satisfied by current capacity ({current_capacity:.1f} RPS)."
        elif predicted_legitimate > current_capacity:
            action = ScalingAction.SCALE
            reason = (
                f"Predicted legitimate demand ({predicted_legitimate:.1f} RPS) exceeds capacity ({current_capacity:.1f} RPS). "
                f"Scaling to {recommended_pods} pods. ({guardrail_reason})"
            )
        elif predicted_legitimate < (current_capacity * 0.5) and recommended_pods < current_pods:
            action = ScalingAction.SCALE
            reason = f"Legitimate demand significantly below current capacity. Scale-down recommended to {recommended_pods} pods."
        else:
            action = ScalingAction.HOLD
            reason = f"Workload is well-balanced. Legitimate demand ({predicted_legitimate:.1f} RPS) is within capacity."

        pod_delta = recommended_pods - baseline_hpa_pods
        composite_confidence = round((traffic.confidence + demand.confidence) / 2.0, 2)

        return ScalingDecision(
            decision_id=str(uuid.uuid4()),
            event_id=traffic.event_id,
            trace_id=context.trace_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            contract_version=settings.CONTRACT_VERSION,
            service_version=settings.SERVICE_VERSION,
            model_version=settings.MODEL_VERSION,
            action=action,
            reason=reason,
            confidence=composite_confidence,
            traffic_risk=traffic.risk_score,
            predicted_legitimate_rps=predicted_legitimate,
            current_capacity_rps=current_capacity,
            current_pods=current_pods,
            recommended_pods=recommended_pods,
            baseline_hpa_recommended_pods=baseline_hpa_pods,
            pod_delta_vs_baseline=pod_delta,
            policy=self.policy_guardrail.policy_name,
            dry_run=True,  # Safety guarantee: always dry-run in bootstrap
            shadow_mode=context.shadow_mode
        )
