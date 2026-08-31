# ADR-001: Three Independent Intelligence Module Architecture

## Status
Accepted

## Context
Traditional cloud autoscalers (such as Kubernetes HPA) react naively to aggregate CPU, memory, or raw request volume. During volumetric DDoS, credential stuffing, or synthetic bot bursts, naive autoscalers scale out infrastructure, incurring massive financial overprovisioning and failure to mitigate the attack.

## Decision
SentinelScale decomposes cloud resource intelligence into three independently owned and decoupled modules:
1. **Module 1 (Traffic Intelligence)**: Assesses telemetry to evaluate traffic legitimacy, security risk, and behavioral anomalies.
2. **Module 2 (Demand Intelligence)**: Forecasts true legitimate workload demand across time horizons.
3. **Module 3 (Platform + Resource Intelligence + Decision Engine)**: Monitors cluster state, computes baseline HPA divergence, and executes deterministic policy guardrails.

Communication between modules is strictly contract-driven via versioned JSON Schemas and validated via Pydantic models. Internal implementations are completely isolated and replaceable without breaking consumers.

## Consequences
- Clean ownership boundaries for multi-developer collaboration.
- Independent deployment cycles and testability.
- No single point of domain coupling.
