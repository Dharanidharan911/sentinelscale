# ADR-002: Decoupled Demand Intelligence and Non-LLM Decision Guardrails

## Status
Accepted

## Context
1. Synchronously coupling Demand Intelligence to Traffic Intelligence introduces cascading latency, tight temporal dependencies, and single points of failure.
2. Ingesting non-deterministic AI models (such as Generative Large Language Models) directly into real-time infrastructure actuation creates safety risks, unbounded latency, hallucinated actions, and unprovable behavior.

## Decision
1. **Asynchronous / Decoupled Demand Intelligence**: Demand Intelligence consumes historical telemetry, metrics, and past traffic distributions independently. It does NOT depend synchronously on real-time Traffic Intelligence evaluations.
2. **Strictly Deterministic, Non-LLM Decision Guardrails**: Infrastructure decisions must be deterministic, mathematically bounded, policy-guarded, and auditable. AI/ML models provide quantitative signals (risk scores, prediction intervals), but the Decision Engine and Policy Guardrail enforce deterministic boundary equations.
3. **No Heavy Distributed Middleware in Bootstrap**: Kafka, Redis, Airflow, and Spark are intentionally excluded from the initial bootstrap to keep the developer loop fast, reliable, and lightweight.

## Consequences
- Resilience against cascading network or service timeouts.
- Provable, deterministic safety invariants for cloud infrastructure.
- Rapid developer onboarding with minimal local footprint.
