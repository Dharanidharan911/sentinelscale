# SentinelScale — Demand Forecasting Benchmark Report (M2-6)

> **Notice**: All scenarios in this benchmark are deterministic synthetic test series,
> explicitly constructed to compare mathematical properties under controlled conditions.
> They do not represent unverified production traffic.

## 1. Scenario-by-Scenario Performance

| Scenario | Model | MAE (RPS) | RMSE (RPS) | Latency (ms) | Interval Coverage | Interval Width (RPS) |
|---|---|---|---|---|---|---|
| `steady_growth` | `demand-v1` | 72.90 | 72.90 | 0.310 | 100% | 259.48 |
| `steady_growth` | `demand-ml-v1` | 60.01 | 60.01 | 1.853 | 100% | 259.48 |
| `steady_decline` | `demand-v1` | 58.32 | 58.32 | 0.163 | 100% | 207.59 |
| `steady_decline` | `demand-ml-v1` | 48.00 | 48.00 | 1.497 | 100% | 207.59 |
| `flat` | `demand-v1` | 3.35 | 3.35 | 0.126 | 100% | 9.88 |
| `flat` | `demand-ml-v1` | 5.08 | 5.08 | 1.685 | 0% | 9.88 |
| `sinusoidal` | `demand-v1` | 64.85 | 64.85 | 0.144 | 0% | 45.26 |
| `sinusoidal` | `demand-ml-v1` | 28.41 | 28.41 | 1.629 | 0% | 45.26 |
| `flash_surge` | `demand-v1` | 114.11 | 114.11 | 0.137 | 100% | 1039.23 |
| `flash_surge` | `demand-ml-v1` | 882.60 | 882.60 | 1.632 | 0% | 1039.23 |
| `noisy` | `demand-v1` | 11.59 | 11.59 | 0.141 | 100% | 96.44 |
| `noisy` | `demand-ml-v1` | 58.50 | 58.50 | 1.696 | 0% | 96.44 |

## 2. Overall Summary Aggregate

| Metric | Baseline (`demand-v1`) | ML Candidate (`demand-ml-v1`) | Delta (ML vs Baseline) |
|---|---|---|---|
| **Overall MAE** | 54.19 RPS | 180.43 RPS | +126.24 RPS |
| **Overall RMSE** | 65.94 RPS | 362.66 RPS | +296.72 RPS |
| **Mean Latency** | 0.1702 ms | 1.6652 ms | +1.4950 ms |
| **Interval Coverage** | 83.3% | 33.3% | -50.0% |
| **Mean Interval Width** | 276.31 RPS | 276.31 RPS | +0.00 RPS |

## 3. Evaluation Conclusion

- **Finding**: While the ML candidate (`demand-ml-v1`) achieved lower error on smooth patterns (`steady_growth`, `steady_decline`, `sinusoidal`), it suffered from explosive projections during step discontinuities (`flash_surge`) and high noise, leading to higher overall MAE (180.43 vs 54.19 RPS) and lower interval coverage (33.3% vs 83.3%).
- **Operational Recommendation**: Baseline model (`demand-v1`) is retained as the default preferred production provider due to its superior surge-resilience, bounded slope clamping, and 10x faster execution (0.17 ms). The ML candidate (`demand-ml-v1`) is preserved and integrated as an opt-in configurable alternative via `FORECAST_MODEL=ml` or `FORECAST_MODEL=demand-ml-v1`.
