"""
SentinelScale — Demand Intelligence — Benchmark Suite Pytest Wrapper (M2-6)
Ensures benchmark suite executes deterministically, measures latency/MAE/RMSE,
and confirms validity of both models.
"""
from benchmarks.benchmark_suite import (
    execute_full_benchmark_suite,
    format_benchmark_markdown_report,
    generate_synthetic_series,
    run_single_benchmark,
)


class TestBenchmarkSuite:

    def test_synthetic_series_generation(self):
        for scenario in ["steady_growth", "steady_decline", "flat", "sinusoidal", "flash_surge", "noisy"]:
            series = generate_synthetic_series(scenario, n_points=25)
            assert len(series) == 25
            for obs in series:
                assert obs.rps >= 0.0
                assert obs.timestamp > 0.0

    def test_single_benchmark_run(self):
        series = generate_synthetic_series("steady_growth", n_points=30)
        b_res, m_res = run_single_benchmark("steady_growth", series, horizon_seconds=300, history_len=15)

        assert b_res.model_version == "demand-v1"
        assert m_res.model_version == "demand-ml-v1"
        assert b_res.mae >= 0.0
        assert m_res.mae >= 0.0
        assert b_res.latency_ms > 0.0
        assert m_res.latency_ms > 0.0
        assert 0.0 <= b_res.coverage_rate <= 1.0
        assert 0.0 <= m_res.coverage_rate <= 1.0

    def test_full_benchmark_suite_execution(self):
        results = execute_full_benchmark_suite()
        assert len(results) == 6
        for scenario, models in results.items():
            assert "baseline" in models
            assert "ml" in models
            assert models["baseline"].sample_count == 20
            assert models["ml"].sample_count == 20

        report = format_benchmark_markdown_report(results)
        assert "# SentinelScale — Demand Forecasting Benchmark Report (M2-6)" in report
        assert "Overall MAE" in report
        assert "Overall RMSE" in report
