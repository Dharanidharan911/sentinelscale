"""Unit tests for the isolated Prometheus telemetry adapter."""
import asyncio

import httpx
import pytest

from app.config.settings import Settings, settings
from app.errors import ProviderUnavailableError
from app.models.demand import ForecastRequest
from app.providers.prometheus_provider import PrometheusDemandProvider
from app.services.forecaster import DemandForecastingService


def _provider(handler):
    return PrometheusDemandProvider(
        base_url="http://prometheus.test",
        query_template='sum(rate(http_requests_total{service="{target_service}"}[1m]))',
        target_service="demo-api",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=1_700_000_300.0,
    )


class TestPrometheusDemandProvider:
    def test_translates_range_query_samples_in_time_order(self):
        def handler(request):
            assert request.url.path == "/api/v1/query_range"
            assert request.url.params["start"] == "1699996700.0"
            assert request.url.params["end"] == "1700000300.0"
            assert request.url.params["step"] == "30"
            assert 'service="demo-api"' in request.url.params["query"]
            return httpx.Response(200, json={
                "status": "success",
                "data": {"resultType": "matrix", "result": [{"values": [
                    ["1700000030", "15.5"], ["1700000000", "10.0"]
                ]}]},
            })

        observations = _provider(handler).get_observations(3600)
        assert [(obs.timestamp, obs.rps) for obs in observations] == [
            (1_700_000_000.0, 10.0), (1_700_000_030.0, 15.5)
        ]

    def test_empty_successful_result_is_no_data_not_zero_demand(self):
        provider = _provider(lambda request: httpx.Response(200, json={
            "status": "success", "data": {"resultType": "matrix", "result": []}
        }))
        assert provider.get_observations(3600) == []

    @pytest.mark.parametrize("payload", [
        {"status": "error", "error": "query failed"},
        {"status": "success", "data": {"resultType": "vector", "result": []}},
        {"status": "success", "data": {"resultType": "matrix", "result": [{"values": [["bad", "4"]]}]}},
        {"status": "success", "data": {"resultType": "matrix", "result": [{"values": [["1700000000", "NaN"]]}]}},
    ])
    def test_malformed_or_unsuccessful_telemetry_is_explicit_failure(self, payload):
        provider = _provider(lambda request: httpx.Response(200, json=payload))
        with pytest.raises(ProviderUnavailableError):
            provider.get_observations(3600)

    def test_transport_failure_is_explicit_provider_failure(self):
        def handler(request):
            raise httpx.ConnectError("offline", request=request)

        with pytest.raises(ProviderUnavailableError, match="Prometheus request failed"):
            _provider(handler).get_observations(3600)

    def test_service_selects_prometheus_only_when_configured(self, monkeypatch):
        class StubProvider:
            name = "StubPrometheus"

            def get_observations(self, window_seconds):
                from app.models.demand import DemandObservation
                return [
                    DemandObservation(timestamp=1_700_000_000, rps=100),
                    DemandObservation(timestamp=1_700_000_030, rps=110),
                ]

        captured = {}

        def provider_factory(**kwargs):
            captured.update(kwargs)
            return StubProvider()

        monkeypatch.setattr(settings, "PROMETHEUS_URL", "http://prometheus.test")
        monkeypatch.setattr("app.services.forecaster.PrometheusDemandProvider", provider_factory)
        forecast = asyncio.run(
            DemandForecastingService().forecast_demand(ForecastRequest(target_service="checkout"))
        )
        assert captured["target_service"] == "checkout"
        assert forecast.predicted_legitimate_rps >= 0.0

    def test_prometheus_configuration_rejects_invalid_timeout(self):
        with pytest.raises(ValueError):
            Settings(PROMETHEUS_TIMEOUT_SECONDS=0)
