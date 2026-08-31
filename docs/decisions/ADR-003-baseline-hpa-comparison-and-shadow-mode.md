# ADR-003: Baseline HPA Comparison Architecture and Shadow Mode

## Status
Accepted

## Context
Deploying autonomous infrastructure controllers into production environments requires continuous empirical validation against established industry baselines (Kubernetes Horizontal Pod Autoscaler - HPA).

## Decision
1. **Shadow Mode First**: All scaling recommendations run in shadow mode (`shadow_mode: true`, `dry_run: true`). Recommendations are evaluated, logged, and compared against live cluster operations without directly mutating Kubernetes replica counts.
2. **First-Class Baseline HPA Calculation**: The Decision Engine continuously calculates what standard reactive HPA would have recommended using the standard formula:
   $$\text{desiredReplicas} = \left\lceil \text{currentReplicas} \times \frac{\text{currentUtilization}}{\text{targetUtilization}} \right\rceil$$
3. **Divergence Metrics**: Emits `pod_delta_vs_baseline` and estimated cost/waste metrics to quantify overprovisioning avoided during attack conditions.

## Consequences
- Zero risk of unintended cluster destabilization during early iterations.
- Clear, empirical evidence of cost savings and security resilience before granting write permissions to the cluster.
