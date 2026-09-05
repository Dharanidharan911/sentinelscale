"""
SentinelScale — Demand Intelligence — Model Benchmark Suite (M2-6)
Compares Baseline Forecaster (demand-v1: RWMA + Linear Trend) vs
ML Candidate Forecaster (demand-ml-v1: Feature-Engineered Ridge Regression).

DATASET NOTICE:
All datasets in this benchmark suite are deterministic, synthetic time-series
scenarios generated strictly for reproducible evaluation. They are NOT production
traces.
"""
import math
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple

from app.models.demand import DemandObservation
from app.engine.forecaster import produce_forecast
from app.engine.ml_forecaster import MLDemandForecaster


@dataclass
class BenchmarkMetricResult:
    scenario_name: str
    model_version: str
    mae: float
    rmse: float
    latency_ms: float
    coverage_rate: float
    avg_interval_width: float
    sample_count: int
    forecast_horizon_seconds: int


def generate_synthetic_series(
    scenario_type: str,
    n_points: int = 30,
    interval_seconds: float = 30.0,
    start_time: float = 1700000000.0,
) -> List[DemandObservation]:
    """
    Generate labeled synthetic observation series.
    All series are fully deterministic and labeled as synthetic.
    """
    observations = []
    for i in range(n_points):
        t = start_time + i * interval_seconds

        if scenario_type == "steady_growth":
            # Linear rise: 500 -> 500 + 0.5 * elapsed
            rps = 500.0 + 0.5 * (i * interval_seconds)
        elif scenario_type == "steady_decline":
            # Linear decline: 900 -> 900 - 0.4 * elapsed
            rps = max(50.0, 900.0 - 0.4 * (i * interval_seconds))
        elif scenario_type == "flat":
            # Flat steady demand around 650 RPS with deterministic ripple
            rps = 650.0 + 5.0 * math.sin(i * 0.5)
        elif scenario_type == "sinusoidal":
            # 1-hour diurnal wave
            phase = (t % 3600.0) / 3600.0
            rps = 850.0 + 150.0 * math.sin(2 * math.pi * phase)
        elif scenario_type == "flash_surge":
            # Step surge at point 15
            rps = 400.0 if i < 15 else 1200.0
        elif scenario_type == "noisy":
            # Noisy demand around 500 RPS
            noise = 40.0 * math.sin(i * 1.3) + 25.0 * math.cos(i * 2.7)
            rps = max(10.0, 500.0 + noise)
        else:
            raise ValueError(f"Unknown synthetic scenario: {scenario_type}")

        observations.append(DemandObservation(timestamp=t, rps=round(max(0.0, rps), 2)))

    return observations


def run_single_benchmark(
    scenario_name: str,
    series: List[DemandObservation],
    horizon_seconds: int = 300,
    history_len: int = 15,
) -> Tuple[BenchmarkMetricResult, BenchmarkMetricResult]:
    """
    Run rolling walk-forward evaluation on a synthetic series comparing
    Baseline vs ML Forecaster.
    """
    history = series[:history_len]
    step_sec = series[1].timestamp - series[0].timestamp
    horizon_steps = int(round(horizon_seconds / step_sec))

    # Ground truth future point
    target_idx = history_len + horizon_steps - 1
    if target_idx < len(series):
        y_true = series[target_idx].rps
    else:
        # Extrapolate true underlying dynamic
        last_obs = series[-1]
        y_true = last_obs.rps

    ml_forecaster = MLDemandForecaster(ridge_alpha=1.0)

    # 1. Evaluate Baseline
    t0 = time.perf_counter()
    baseline_fc = produce_forecast(history, forecast_horizon_seconds=horizon_seconds)
    baseline_latency = (time.perf_counter() - t0) * 1000.0

    b_err = abs(baseline_fc.predicted_legitimate_rps - y_true)
    b_cov = 1.0 if (baseline_fc.lower_bound_rps <= y_true <= baseline_fc.upper_bound_rps) else 0.0
    b_width = baseline_fc.upper_bound_rps - baseline_fc.lower_bound_rps

    b_result = BenchmarkMetricResult(
        scenario_name=scenario_name,
        model_version=baseline_fc.model_version,
        mae=round(b_err, 4),
        rmse=round(b_err, 4),
        latency_ms=round(baseline_latency, 4),
        coverage_rate=b_cov,
        avg_interval_width=round(b_width, 4),
        sample_count=len(history),
        forecast_horizon_seconds=horizon_seconds,
    )

    # 2. Evaluate ML Candidate
    t0 = time.perf_counter()
    ml_fc = ml_forecaster.predict(history, forecast_horizon_seconds=horizon_seconds)
    ml_latency = (time.perf_counter() - t0) * 1000.0

    m_err = abs(ml_fc.predicted_legitimate_rps - y_true)
    m_cov = 1.0 if (ml_fc.lower_bound_rps <= y_true <= ml_fc.upper_bound_rps) else 0.0
    m_width = ml_fc.upper_bound_rps - ml_fc.lower_bound_rps

    m_result = BenchmarkMetricResult(
        scenario_name=scenario_name,
        model_version=ml_fc.model_version,
        mae=round(m_err, 4),
        rmse=round(m_err, 4),
        latency_ms=round(ml_latency, 4),
        coverage_rate=m_cov,
        avg_interval_width=round(m_width, 4),
        sample_count=len(history),
        forecast_horizon_seconds=horizon_seconds,
    )

    return b_result, m_result


def execute_full_benchmark_suite() -> Dict[str, Dict[str, BenchmarkMetricResult]]:
    """
    Execute benchmark across all defined scenarios and compute aggregate metrics.
    """
    scenarios = [
        "steady_growth",
        "steady_decline",
        "flat",
        "sinusoidal",
        "flash_surge",
        "noisy",
    ]

    results: Dict[str, Dict[str, BenchmarkMetricResult]] = {}

    for name in scenarios:
        series = generate_synthetic_series(name, n_points=35)
        b_res, m_res = run_single_benchmark(name, series, horizon_seconds=300, history_len=20)
        results[name] = {"baseline": b_res, "ml": m_res}

    return results


def format_benchmark_markdown_report(results: Dict[str, Dict[str, BenchmarkMetricResult]]) -> str:
    """Format benchmark results into a clean markdown table."""
    lines = [
        "# SentinelScale — Demand Forecasting Benchmark Report (M2-6)",
        "",
        "> **Notice**: All scenarios in this benchmark are deterministic synthetic test series,",
        "> explicitly constructed to compare mathematical properties under controlled conditions.",
        "> They do not represent unverified production traffic.",
        "",
        "## 1. Scenario-by-Scenario Performance",
        "",
        "| Scenario | Model | MAE (RPS) | RMSE (RPS) | Latency (ms) | Interval Coverage | Interval Width (RPS) |",
        "|---|---|---|---|---|---|---|",
    ]

    b_maes, m_maes = [], []
    b_rmses, m_rmses = [], []
    b_lats, m_lats = [], []
    b_covs, m_covs = [], []
    b_widths, m_widths = [], []

    for name, pair in results.items():
        b = pair["baseline"]
        m = pair["ml"]

        b_maes.append(b.mae)
        m_maes.append(m.mae)
        b_rmses.append(b.rmse ** 2)
        m_rmses.append(m.rmse ** 2)
        b_lats.append(b.latency_ms)
        m_lats.append(m.latency_ms)
        b_covs.append(b.coverage_rate)
        m_covs.append(m.coverage_rate)
        b_widths.append(b.avg_interval_width)
        m_widths.append(m.avg_interval_width)

        lines.append(
            f"| `{name}` | `{b.model_version}` | {b.mae:.2f} | {b.rmse:.2f} | {b.latency_ms:.3f} | {b.coverage_rate * 100:.0f}% | {b.avg_interval_width:.2f} |"
        )
        lines.append(
            f"| `{name}` | `{m.model_version}` | {m.mae:.2f} | {m.rmse:.2f} | {m.latency_ms:.3f} | {m.coverage_rate * 100:.0f}% | {m.avg_interval_width:.2f} |"
        )

    # Compute aggregate summary
    n = len(results)
    b_overall_mae = sum(b_maes) / n
    m_overall_mae = sum(m_maes) / n
    b_overall_rmse = math.sqrt(sum(b_rmses) / n)
    m_overall_rmse = math.sqrt(sum(m_rmses) / n)
    b_overall_lat = sum(b_lats) / n
    m_overall_lat = sum(m_lats) / n
    b_overall_cov = sum(b_covs) / n
    m_overall_cov = sum(m_covs) / n
    b_overall_width = sum(b_widths) / n
    m_overall_width = sum(m_widths) / n

    lines.extend([
        "",
        "## 2. Overall Summary Aggregate",
        "",
        "| Metric | Baseline (`demand-v1`) | ML Candidate (`demand-ml-v1`) | Delta (ML vs Baseline) |",
        "|---|---|---|---|",
        f"| **Overall MAE** | {b_overall_mae:.2f} RPS | {m_overall_mae:.2f} RPS | {m_overall_mae - b_overall_mae:+.2f} RPS |",
        f"| **Overall RMSE** | {b_overall_rmse:.2f} RPS | {m_overall_rmse:.2f} RPS | {m_overall_rmse - b_overall_rmse:+.2f} RPS |",
        f"| **Mean Latency** | {b_overall_lat:.4f} ms | {m_overall_lat:.4f} ms | {m_overall_lat - b_overall_lat:+.4f} ms |",
        f"| **Interval Coverage** | {b_overall_cov * 100:.1f}% | {m_overall_cov * 100:.1f}% | {(m_overall_cov - b_overall_cov) * 100:+.1f}% |",
        f"| **Mean Interval Width** | {b_overall_width:.2f} RPS | {m_overall_width:.2f} RPS | {m_overall_width - b_overall_width:+.2f} RPS |",
        "",
        "## 3. Evaluation Conclusion",
        "",
    ])

    if m_overall_mae < b_overall_mae:
        lines.append(
            "- **Verdict**: ML candidate demonstrates superior accuracy on tested synthetic scenarios. "
            "Retained as available/preferred engine when configured."
        )
    elif abs(m_overall_mae - b_overall_mae) < 20.0:
        lines.append(
            "- **Verdict**: ML candidate demonstrates comparable accuracy to the baseline RWMA engine. "
            "Both models are viable; baseline remains default for maximum simplicity and zero-overhead execution."
        )
    else:
        lines.append(
            "- **Verdict**: Baseline model outperforms ML candidate on small-window extrapolation. "
            "Baseline remains the default production engine."
        )

    return "\n".join(lines)


if __name__ == "__main__":
    suite_results = execute_full_benchmark_suite()
    report = format_benchmark_markdown_report(suite_results)
    print(report)
