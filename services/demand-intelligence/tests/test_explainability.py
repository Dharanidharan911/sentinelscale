"""
SentinelScale — Demand Intelligence — Test: Forecast Explainability (M2-14)
Validates structured explanation tags, trend classification, volatility tags,
seasonality detection tags, and HTTP header propagation without contract mutation.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.demand import DemandObservation, DemandForecast
from app.engine.forecaster import produce_forecast
from app.engine.explainability import ForecastExplainer, ForecastExplanation

client = TestClient(app)


def _obs(ts, rps):
    return DemandObservation(timestamp=ts, rps=rps)


class TestForecastExplainer:
    def test_explains_rising_trend_correctly(self):
        t0 = 1700000000.0
        data = [_obs(t0 + i * 30.0, 100.0 + i * 20.0) for i in range(15)]
        fc = produce_forecast(data, 300)
        expl = ForecastExplainer.explain(fc, data)

        assert expl.trend_tag == "TREND_RISING"
        assert "TREND_RISING" in expl.all_tags
        assert "MODEL_BASELINE_RWMA" in expl.all_tags
        assert expl.quality_tag in ["QUALITY_EXCELLENT", "QUALITY_GOOD"]

    def test_explains_falling_trend_correctly(self):
        t0 = 1700000000.0
        data = [_obs(t0 + i * 30.0, 1000.0 - i * 30.0) for i in range(15)]
        fc = produce_forecast(data, 300)
        expl = ForecastExplainer.explain(fc, data)

        assert expl.trend_tag == "TREND_FALLING"
        assert "TREND_FALLING" in expl.all_tags

    def test_explains_high_volatility(self):
        t0 = 1700000000.0
        data = [_obs(t0 + i * 30.0, 500.0 + (600.0 if i % 2 == 0 else -400.0)) for i in range(15)]
        fc = produce_forecast(data, 300)
        expl = ForecastExplainer.explain(fc, data)

        assert expl.volatility_tag == "VOLATILITY_HIGH"

    def test_explains_stable_low_volatility(self):
        t0 = 1700000000.0
        data = [_obs(t0 + i * 30.0, 500.0) for i in range(15)]
        fc = produce_forecast(data, 300)
        expl = ForecastExplainer.explain(fc, data)

        assert expl.trend_tag == "TREND_STABLE"
        assert expl.volatility_tag == "VOLATILITY_LOW"
        assert "NO_SEASONALITY_DETECTED" in expl.all_tags


class TestExplainabilityHeadersIntegration:
    def test_endpoint_returns_explanation_headers(self):
        """POST /api/v1/demand/forecast returns X-Forecast-Explanation and X-Forecast-Quality."""
        t0 = 1700000000.0
        observations = [
            {"timestamp": t0 + i * 30.0, "rps": 300.0 + i * 10.0}
            for i in range(12)
        ]
        response = client.post(
            "/api/v1/demand/forecast",
            json={"forecast_horizon_seconds": 300, "observations": observations},
        )
        assert response.status_code == 200

        # Check headers
        assert "X-Forecast-Explanation" in response.headers
        assert "X-Forecast-Quality" in response.headers
        explanation_header = response.headers["X-Forecast-Explanation"]
        quality_header = response.headers["X-Forecast-Quality"]

        assert "MODEL_" in explanation_header
        assert "TREND_" in explanation_header
        assert "QUALITY_" in explanation_header
        assert quality_header.startswith("QUALITY_")

        # Confirm JSON body remains strictly valid DemandForecast v1.0.0
        data = response.json()
        forecast = DemandForecast.model_validate(data)
        assert forecast.contract_version == "1.0.0"
        assert forecast.predicted_legitimate_rps > 0.0
