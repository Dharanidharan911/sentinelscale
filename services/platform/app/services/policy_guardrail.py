import math
from app.config.settings import settings
from app.models.context import DecisionContext


class PolicyGuardrail:
    """
    Deterministic Safety Policy Guardrails for Infrastructure Scaling.
    Guarantees bounds on scaling decisions, prevents flapping, and enforces dry-run safety.
    Strictly non-LLM, mathematical, and deterministic.
    """

    def __init__(self):
        self.policy_name = "default-safe-guardrail-v1"

    def apply_guardrails(
        self,
        raw_recommended_pods: int,
        context: DecisionContext
    ) -> tuple[int, str]:
        """
        Enforces min/max boundaries and step limits.
        Returns: (safe_recommended_pods, policy_explanation)
        """
        overrides = context.policy_overrides
        min_pods = overrides.min_pods if overrides and overrides.min_pods is not None else settings.DEFAULT_MIN_PODS
        max_pods = overrides.max_pods if overrides and overrides.max_pods is not None else settings.DEFAULT_MAX_PODS
        current_pods = max(1, context.resource_state.running_pods)

        bounded_pods = raw_recommended_pods

        # Enforce Minimum Replicas
        if bounded_pods < min_pods:
            return min_pods, f"Clamped to minimum policy threshold ({min_pods} pods)."

        # Enforce Maximum Replicas
        if bounded_pods > max_pods:
            return max_pods, f"Clamped to maximum policy safety ceiling ({max_pods} pods)."

        # Rate of change guardrail (Max 2x scale-up per decision step)
        max_step_up = current_pods * 2
        if bounded_pods > max_step_up:
            return max_step_up, f"Restricted by step-up surge protection (+{max_step_up - current_pods} pods max)."

        return bounded_pods, "Within standard policy safety bounds."
