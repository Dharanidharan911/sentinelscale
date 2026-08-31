# SentinelScale Shadow-Mode & Baseline Experiments

## Purpose
This directory contains experimental scenario definitions, replay benchmarks, and validation configs for shadow-mode evaluations against the Kubernetes Horizontal Pod Autoscaler (HPA).

## Key Concepts
1. **Shadow Mode**: SentinelScale observes live traffic alongside the default HPA autoscaler, logging decisions without modifying replicas.
2. **Baseline Comparison**: Compares the cost, pod count, and p95 latency of SentinelScale vs. Reactive HPA during simulated malicious bursts.
3. **Reproducibility**: Datasets and scenario profiles allow repeatable offline model verification before promoting new model versions (e.g. from `traffic-v0` to `traffic-v1`).
