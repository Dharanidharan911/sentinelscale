# HPA vs. SentinelScale Formal Comparative Evaluation

## 1. Overview & Purpose

SentinelScale solves the fundamental vulnerability of traditional Horizontal Pod Autoscaling (HPA) under malicious or non-business traffic surges (Economic Denial of Sustainability / EDoS). 

Traditional Kubernetes HPA scales replicas strictly based on observed raw metrics (such as average CPU utilization or request rate). When attack traffic (DDoS, scrapers, HTTP floods) drives up pod CPU utilization, HPA reactively provisions more pods, scaling up infrastructure costs while rewarding the attacker's objectives.

SentinelScale decouples **legitimate demand** from **malicious/suspicious surge traffic**, calculating required capacity from verified business demand while holding or mitigating malicious load.

The **HPA vs. SentinelScale Evaluation Layer** is a deterministic, read-only analytical evaluation framework that quantifies the difference between HPA and SentinelScale under identical observed operational conditions.

---

## 2. Architectural Comparison

```
                      [Observed Workload State]
                                  │
          ┌───────────────────────┴───────────────────────┐
          ▼                                               ▼
[Traditional Reactive HPA]                      [SentinelScale Engine]
- Inputs: Raw CPU / Total Traffic               - Inputs: Traffic Assessment + Legitimate Demand
- Formula: ceil[current * (cpu / target)]       - Formula: ceil[legitimate_rps / pod_rps_capacity]
- Security Blind: YES                            - Security Aware: YES
          │                                               │
          └───────────────────────┬───────────────────────┘
                                  ▼
                  [Formal Comparative Evaluator]
                                  │
     ┌────────────────────────────┼────────────────────────────┐
     ▼                            ▼                            ▼
[Categorization]          [Replica Deltas]             [Savings Metrics]
- ALIGNED                 - replica_delta              - pod_hours_saved/hr
- PREVENTS_UNNECESSARY    - absolute_replica_delta     - unnecessary_scale_up
- PROACTIVELY_SCALES      - direction                  - capacity_satisfied
- SCALE_DOWN_DIFFERENCE
- UNCERTAIN
```

---

## 3. Evaluation Categories & Deterministic Rules

| Category | Trigger Conditions | Behavioral Explanation |
| :--- | :--- | :--- |
| `ALIGNED` | $S_{pods} = HPA_{pods}$ | Both systems recommend identical replica counts under clean or balanced traffic. |
| `SENTINELSCALE_PREVENTS_UNNECESSARY_SCALE` | $HPA_{pods} > S_{pods}$, Traffic Risk $\ge 0.70$, Legitimate Demand $\le$ Capacity | HPA reactively scales up on attack-driven CPU spikes, whereas SentinelScale detects that legitimate demand is satisfied by existing capacity and suppresses scale-out. |
| `SENTINELSCALE_PROACTIVELY_SCALES` | Legitimate Demand $>$ Current Capacity, $S_{pods} > Current_{pods}$ | SentinelScale proactively scales out to satisfy surging legitimate business demand, even if reactive HPA metric lag has not yet caught up. |
| `SCALE_DOWN_DIFFERENCE` | $S_{pods} < Current_{pods}$ and $S_{pods} < HPA_{pods}$ | SentinelScale identifies that legitimate demand is well below capacity and recommends safe scale-down, whereas HPA maintains excess replicas. |
| `UNCERTAIN` | Composite Confidence $< 0.50$ | Telemetry or forecast inputs are degraded; comparative assessment marked uncertain to avoid ungrounded conclusions. |

---

## 4. Quantitative Metrics & Cost Savings

The evaluation layer computes the following metrics for every comparative cycle:

- `replica_delta`: Signed integer ($S_{pods} - HPA_{pods}$). Negative values indicate SentinelScale avoided excess pod provisioning.
- `absolute_replica_delta`: $|S_{pods} - HPA_{pods}|$.
- `estimated_pod_hours_saved_per_hour`: $\max(0, HPA_{pods} - S_{pods})$. Represents direct infrastructure hour savings per elapsed operational hour.
- `unnecessary_scale_up_signal`: Boolean flag set to `True` strictly when HPA scales out on attack traffic while legitimate demand fits existing capacity.
- `capacity_satisfied`: Boolean flag indicating whether predicted legitimate RPS is within existing cluster capacity.
- `suppression_reason`: Explicit diagnostic string stating the exact risk score, legitimate demand, and avoided pod count.

---

## 5. API Endpoints

### 5.1 POST `/api/v1/evaluation/evaluate`
Direct comparative evaluation from a given `DecisionContext`.
- **Request**: `DecisionContext` JSON payload
- **Response**: `EvaluationResult`

### 5.2 GET `/api/v1/evaluation/hpa-vs-sentinelscale`
Evaluates a specific historical observation or the latest recorded cycle in the audit history store.
- **Parameters**: `observation_id` (optional string)
- **Response**: `EvaluationResult`

---

## 6. Safety Invariants

- **Read-Only / Dry-Run**: All evaluation results enforce `dry_run=True` and `shadow_mode=True`.
- **Zero Kubernetes Mutations**: Evaluator neither queries nor mutates live cluster resources directly.
- **Deterministic**: Logic is strictly mathematical and rule-based without non-deterministic heuristics.

