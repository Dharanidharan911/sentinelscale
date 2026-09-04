# Phase 5C — Adaptive Predictive Intelligence

## Overview

Phase 5C introduces a **deterministic, read-only predictive intelligence layer** to SentinelScale. Building on the historical decision records from Phase 4B, Prometheus metrics from Phase 4C, and the behavioral baseline and anomaly detection engine from Phase 5B, Phase 5C answers the question:

> *"What is likely to happen next based on recent observed behavior?"*

The predictive intelligence layer projects key operational signals into short-term future horizons, evaluates capacity headroom and exhaustion risk, and provides advisory replica recommendations with comparative HPA divergence analysis.

---

## Key Principles & Design Constraints

1. **Deterministic Mathematics Only**:
   - Zero ML/LLM models, neural nets, or external statistical dependencies.
   - Built entirely with Python's standard library (`math`, `statistics`).
   - Uses Ordinary Least Squares (OLS) linear trend fitting parameterized by elapsed time ($t_i - t_0$).

2. **Strict Read-Only Isolation**:
   - Purely analytical and advisory.
   - Zero mutations to Kubernetes, HPA, deployment replicas, or system state (`dry_run=True`, `shadow_mode=True` strictly preserved).
   - Zero feedback into the real-time actuation path (`DecisionEngine` and `PolicyGuardrail`).

3. **Robust Domain Guardrails & Outlier Resistance**:
   - Outlier resistance via residual standard deviation thresholding ($|r_i| > 3\sigma_{\text{res}}$), deterministically degrading confidence to `LOW` or `MEDIUM`.
   - Domain-specific boundary clamping:
     - All predictions $\ge 0.0$.
     - `traffic_risk` clamped to $[0.0, 1.0]$.
     - Pod metrics (`recommended_pods`, `current_pods`, `baseline_hpa_recommended_pods`) clamped to $\ge 1.0$.
     - `pod_delta_vs_baseline` signed (can be negative).
   - Cold start protection: requires $\ge 5$ valid historical observations; otherwise returns `status="INSUFFICIENT_DATA"`.
   - Stale data detection: flags observations older than 10 minutes (600s) as `status="STALE"` and degrades confidence.

4. **Zero Contract Changes**:
   - Existing frozen JSON schemas in `contracts/` remain 100% untouched.

---

## Architecture & Data Flow

```
[Historical Store / SQLite] ──► [Historical Records (Windowed)]
                                        │
                                        ▼
                         [PredictiveIntelligenceService]
                                        │
               ┌────────────────────────┼────────────────────────┐
               ▼                        ▼                        ▼
       [OLS Trend Fitting]     [Capacity Pressure]     [Advisory Pods]
     - Slope per sec          - Utilization Ratio     - Recommended Pods
     - R² Goodness of Fit     - Headroom (RPS)        - Projected HPA Pods
     - Outlier Detection      - Pressure Category     - Delta vs HPA Baseline
     - Direction & Confidence   (NORMAL/ELEVATED/
                                 HIGH/CRITICAL)
               │                        │                        │
               └────────────────────────┼────────────────────────┘
                                        ▼
                            [PredictiveForecast]
                                        │
                                        ▼
                    GET /api/v1/intelligence/predictions
```

---

## Forecasted Signals

1. `predicted_legitimate_rps` — Legitimate demand rate.
2. `traffic_risk` — Traffic risk score ($[0.0, 1.0]$).
3. `current_capacity_rps` — Cluster throughput capacity.
4. `recommended_pods` — SentinelScale recommended replica count.
5. `current_pods` — Current active pod count.
6. `baseline_hpa_recommended_pods` — Reactive HPA recommended replica count.
7. `pod_delta_vs_baseline` — Difference between SentinelScale and HPA ($ rec - hpa $).

---

## API Specification

### `GET /api/v1/intelligence/predictions`

#### Query Parameters
- `window` (optional): Pre-defined lookback window (`5m`, `15m`, `1h`, `6h`, `24h`, `7d`).
- `horizon` (optional): Forecast horizon (`30s`, `1m`, `5m`, `15m`). Defaults to `5m` (300s).
- `horizon_seconds` (optional): Explicit forecast horizon in seconds (10 to 3600s).
- `start_time` (optional): ISO-8601 start timestamp for custom time range.
- `end_time` (optional): ISO-8601 end timestamp for custom time range.
- `observation_id` (optional): Specific reference observation ID to anchor prediction.

#### Response Structure (`PredictiveForecast`)
```json
{
  "generated_at": "2026-09-04T17:10:00.000000+00:00",
  "baseline_window": "15m",
  "start_time": "2026-09-04T16:55:00.000000+00:00",
  "end_time": "2026-09-04T17:10:00.000000+00:00",
  "forecast_horizon_seconds": 300,
  "status": "OK",
  "data_quality": "GOOD",
  "sample_count": 15,
  "minimum_required_samples": 5,
  "latest_observation_time": "2026-09-04T17:09:45.000000+00:00",
  "signals": {
    "predicted_legitimate_rps": {
      "signal": "predicted_legitimate_rps",
      "status": "OK",
      "sample_count": 15,
      "latest_value": 1200.0,
      "predicted_value": 1450.0,
      "delta": 250.0,
      "delta_percent": 20.8,
      "trend": "INCREASING",
      "confidence": "HIGH",
      "mean": 1050.0,
      "slope_per_second": 0.8333,
      "forecast_horizon_seconds": 300,
      "interpretation": "predicted_legitimate_rps is projected to increase by +250.0 (+20.8%) to 1450.0 over the next 300s."
    }
  },
  "pressure": {
    "predicted_legitimate_rps": 1450.0,
    "predicted_capacity_rps": 2100.0,
    "predicted_capacity_utilization": 0.69,
    "level": "ELEVATED",
    "interpretation": "Forecasted demand (1450.0 RPS) creates ELEVATED pressure (69.0% utilization) on capacity (2100.0 RPS)."
  },
  "pods": {
    "predicted_recommended_pods": 5,
    "predicted_hpa_pods": 8,
    "predicted_delta_vs_hpa": -3,
    "min_pods": 2,
    "max_pods": 20,
    "interpretation": "SentinelScale projects conservative requirement of 5 pods (HPA projected at 8 pods; suppressed overprovisioning of 3 pods)."
  },
  "explanation": "Forecast successfully computed across 7 operational signals for horizon 300s."
}
```

---

## Test Verification

Phase 5C includes 38 comprehensive unit, mathematical, edge-case, and API integration tests in `services/platform/tests/test_predictive_intelligence.py`.

Overall suite verification:
- Demo API: **9 passed**
- Traffic Intelligence: **18 passed**
- Demand Intelligence: **5 passed**
- Platform & Decision Engine: **185 passed, 1 skipped**
- **Total: 217 passed, 1 skipped, 0 failed**

