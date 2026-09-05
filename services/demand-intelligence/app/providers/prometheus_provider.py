"""Prometheus-backed demand provider.

The adapter is deliberately isolated from the forecast engine: it translates
Prometheus range-query samples into ``DemandObservation`` instances and turns
transport or response failures into explicit provider failures.
"""
import math
import time
from typing import Any, List, Optional

import httpx

from app.errors import ProviderUnavailableError
from app.models.demand import DemandObservation
from app.providers.base import DemandProvider


class PrometheusDemandProvider(DemandProvider):
    """Retrieve legitimate RPS samples from the Prometheus HTTP API."""

    def __init__(
        self,
        base_url: str,
        query_template: str,
        target_service: str,
        step_seconds: int = 30,
        timeout_seconds: float = 5.0,
        client: Optional[httpx.Client] = None,
        now: Optional[float] = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._query_template = query_template
        self._target_service = target_service
        self._step_seconds = step_seconds
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._now = now

    @property
    def name(self) -> str:
        return "PrometheusDemandProvider"

    def get_observations(self, window_seconds: int) -> List[DemandObservation]:
        if not self._base_url:
            raise ProviderUnavailableError(self.name, "PROMETHEUS_URL is not configured")
        if window_seconds <= 0:
            raise ProviderUnavailableError(self.name, "window_seconds must be positive")

        end = self._now if self._now is not None else time.time()
        # PromQL itself uses braces for label matchers, so ``str.format`` is
        # unsuitable here. Only the documented placeholder is substituted.
        query = self._query_template.replace(
            "{target_service}", self._escape_label_value(self._target_service)
        )
        params = {
            "query": query,
            "start": end - window_seconds,
            "end": end,
            "step": self._step_seconds,
        }

        try:
            if self._client is not None:
                response = self._client.get(
                    f"{self._base_url}/api/v1/query_range",
                    params=params,
                    timeout=self._timeout_seconds,
                )
            else:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.get(
                        f"{self._base_url}/api/v1/query_range", params=params
                    )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailableError(self.name, f"Prometheus request failed: {exc}") from exc

        return self._parse_response(payload)

    def _parse_response(self, payload: Any) -> List[DemandObservation]:
        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise ProviderUnavailableError(self.name, "Prometheus returned an unsuccessful response")

        data = payload.get("data")
        if not isinstance(data, dict) or data.get("resultType") != "matrix":
            raise ProviderUnavailableError(self.name, "Prometheus returned an invalid range-query payload")
        result = data.get("result")
        if not isinstance(result, list):
            raise ProviderUnavailableError(self.name, "Prometheus result is malformed")

        samples: dict[float, float] = {}
        try:
            for series in result:
                if not isinstance(series, dict) or not isinstance(series.get("values"), list):
                    raise ValueError("series values are missing")
                for sample in series["values"]:
                    if not isinstance(sample, list) or len(sample) != 2:
                        raise ValueError("sample must contain timestamp and value")
                    timestamp, rps = float(sample[0]), float(sample[1])
                    if not math.isfinite(timestamp) or timestamp <= 0:
                        raise ValueError("sample timestamp is invalid")
                    if not math.isfinite(rps) or rps < 0:
                        raise ValueError("sample RPS is invalid")
                    # A sum query normally produces one series. If a custom query
                    # produces several, combine equal-timestamp series explicitly.
                    samples[timestamp] = samples.get(timestamp, 0.0) + rps
        except (TypeError, ValueError, OverflowError) as exc:
            raise ProviderUnavailableError(self.name, f"Prometheus returned malformed telemetry: {exc}") from exc

        return [
            DemandObservation(timestamp=timestamp, rps=rps)
            for timestamp, rps in sorted(samples.items())
        ]

    @staticmethod
    def _escape_label_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')
