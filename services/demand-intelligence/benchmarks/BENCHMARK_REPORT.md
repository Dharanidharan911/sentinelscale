# SentinelScale — Demand Forecasting Benchmark Report (M2-6)

> **Notice**: All scenarios in this benchmark are deterministic synthetic test series,
> explicitly constructed to compare mathematical properties under controlled conditions.
> They do not represent unverified production traffic.

## 1. Scenario-by-Scenario Performance

| Scenario | Model | MAE (RPS) | RMSE (RPS) | Latency (ms) | Interval Coverage | Interval Width (RPS) |
|---|---|---|---|---|---|---|
| `steady_growth` | `demand-v1` | 72.90 | 72.90 | 0.512 | 100% | 320.58 |
| `steady_growth` | `demand-ml-v1` | 60.01 | 60.01 | 2.026 | 100% | 320.58 |
| `steady_decline` | `demand-v1` | 58.32 | 58.32 | 0.348 | 100% | 256.46 |
| `steady_decline` | `demand-ml-v1` | 48.00 | 48.00 | 1.583 | 100% | 256.46 |
| `flat` | `demand-v1` | 3.35 | 3.35 | 0.276 | 100% | 12.21 |
| `flat` | `demand-ml-v1` | 5.08 | 5.08 | 1.685 | 100% | 12.21 |
| `sinusoidal` | `demand-v1` | 64.85 | 64.85 | 0.255 | 0% | 55.92 |
| `sinusoidal` | `demand-ml-v1` | 28.41 | 28.41 | 1.660 | 0% | 55.92 |
| `flash_surge` | `demand-v1` | 114.11 | 114.11 | 0.359 | 100% | 1283.91 |
| `flash_surge` | `demand-ml-v1` | 882.60 | 882.60 | 1.634 | 0% | 1283.91 |
| `noisy` | `demand-v1` | 14.70 | 14.70 | 0.325 | 100% | 119.15 |
| `noisy` | `demand-ml-v1` | 58.50 | 58.50 | 1.644 | 100% | 119.15 |

## 2. Overall Summary Aggregate

| Metric | Baseline (`demand-v1`) | ML Candidate (`demand-ml-v1`) | Delta (ML vs Baseline) |
|---|---|---|---|
| **Overall MAE** | 54.71 RPS | 180.43 RPS | +125.73 RPS |
| **Overall RMSE** | 66.04 RPS | 362.66 RPS | +296.62 RPS |
| **Mean Latency** | 0.3458 ms | 1.7051 ms | +1.3593 ms |
| **Interval Coverage** | 83.3% | 66.7% | -16.7% |
| **Mean Interval Width** | 341.37 RPS | 341.37 RPS | +0.00 RPS |

## 3. Evaluation Conclusion

- **Finding**: With horizon and regularity dilated prediction intervals (M2-9), the ML candidate (`demand-ml-v1`) interval coverage improved from 33.3% to 66.7% while maintaining lower error on steady growth and decline. However, during sharp step discontinuities (`flash_surge`), baseline (`demand-v1`) remains more resilient (MAE 54.71 vs 180.43 RPS) and 5x faster in execution latency (0.35 ms vs 1.71 ms).
- **Operational Recommendation**: Baseline model (`demand-v1`) is retained as the default preferred production provider. The ML candidate (`demand-ml-v1`) is preserved and integrated as an opt-in configurable alternative via `FORECAST_MODEL=ml`.
