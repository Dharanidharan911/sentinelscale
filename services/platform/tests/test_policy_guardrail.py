import pytest

from app.config.settings import settings
from app.models.context import PolicyOverrides
from app.services.policy_guardrail import PolicyGuardrail
from tests.fixtures_decision import make_decision_context, make_resource_state


def make_guardrail_context(
    running_pods: int = 4,
    min_pods: int = None,
    max_pods: int = None,
):
    overrides = None
    if min_pods is not None or max_pods is not None:
        overrides = PolicyOverrides(
            min_pods=min_pods,
            max_pods=max_pods,
        )
    return make_decision_context(
        resource_state=make_resource_state(running_pods=running_pods),
        policy_overrides=overrides,
    )


def test_guardrail_within_bounds_returns_unchanged():
    guardrail = PolicyGuardrail()
    context = make_guardrail_context(running_pods=4)  # min=2, max=20 by default

    safe_pods, reason = guardrail.apply_guardrails(raw_recommended_pods=8, context=context)

    assert safe_pods == 8
    assert "Within standard policy safety bounds" in reason


def test_guardrail_enforces_minimum_replicas():
    guardrail = PolicyGuardrail()
    context = make_guardrail_context(running_pods=4)  # default min_pods=2

    safe_pods, reason = guardrail.apply_guardrails(raw_recommended_pods=1, context=context)

    assert safe_pods == settings.DEFAULT_MIN_PODS
    assert "minimum policy threshold" in reason


def test_guardrail_enforces_maximum_replicas():
    guardrail = PolicyGuardrail()
    context = make_guardrail_context(running_pods=4)  # default max_pods=20

    safe_pods, reason = guardrail.apply_guardrails(raw_recommended_pods=999, context=context)

    assert safe_pods == settings.DEFAULT_MAX_PODS
    assert "maximum policy safety ceiling" in reason


def test_guardrail_respects_policy_overrides_min_and_max():
    guardrail = PolicyGuardrail()
    context = make_guardrail_context(running_pods=4, min_pods=5, max_pods=6)

    min_clamped, min_reason = guardrail.apply_guardrails(raw_recommended_pods=1, context=context)
    max_clamped, max_reason = guardrail.apply_guardrails(raw_recommended_pods=100, context=context)

    assert min_clamped == 5
    assert "minimum policy threshold (5 pods)" in min_reason
    assert max_clamped == 6
    assert "maximum policy safety ceiling (6 pods)" in max_reason


def test_guardrail_step_up_surge_protection():
    """Unsafe 5x jump must be constrained to 2x the current replica count.

    Guardrail order is: min clamp -> max ceiling -> 2x step-up. To genuinely
    reach the step-up rule, max_pods must be high enough that the raw
    recommendation is NOT intercepted by the ceiling first.
    """
    guardrail = PolicyGuardrail()
    # running_pods=4 -> 2x step-up = 8; max_pods=50 so raw 20 passes the ceiling
    context = make_guardrail_context(running_pods=4, max_pods=50)

    safe_pods, reason = guardrail.apply_guardrails(raw_recommended_pods=20, context=context)

    assert safe_pods == 8
    assert "step-up surge protection" in reason


def test_guardrail_is_deterministic():
    """Same input must always produce the same bounded output."""
    guardrail = PolicyGuardrail()
    context = make_guardrail_context(running_pods=4)

    results = {guardrail.apply_guardrails(raw_recommended_pods=50, context=context)[0] for _ in range(10)}

    assert len(results) == 1


def test_guardrail_has_stable_policy_name():
    guardrail = PolicyGuardrail()
    assert isinstance(guardrail.policy_name, str)
    assert len(guardrail.policy_name) > 0
