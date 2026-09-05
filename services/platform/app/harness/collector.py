"""
SentinelScale — Telemetry Observation Collector
Aggregates raw ObservedRequestEvents into a schema-valid TrafficTelemetryInput for Module 1.
"""
from collections import Counter
from typing import List, Optional
from app.harness.models import ObservedRequestEvent
from app.models.traffic_contract import StatusCodeDistribution, TrafficTelemetryInput


# Known bot / tool signatures for UA classification
BOT_UA_PATTERNS = [
    "curl",
    "python-requests",
    "go-http-client",
    "scrapy",
    "apache-httpclient",
    "wget",
    "postman",
    "httpclient",
    "bot",
    "crawler",
    "spider",
]


class TelemetryCollector:
    """
    Transforms empirical HTTP request observations into structured traffic telemetry.
    Every output field has strict provenance derived from actual ObservedRequestEvents.
    """

    @staticmethod
    def is_bot_user_agent(user_agent: str) -> bool:
        """Determines if a User-Agent string is a non-standard / automated script / bot."""
        if not user_agent or not user_agent.strip():
            return True
        ua_lower = user_agent.lower()
        return any(pattern in ua_lower for pattern in BOT_UA_PATTERNS)

    @classmethod
    def collect(
        cls,
        events: List[ObservedRequestEvent],
        window_seconds: int = 60,
        baseline_rps: Optional[float] = None,
    ) -> TrafficTelemetryInput:
        """
        Aggregate a sequence of observed HTTP request events over the observation window.
        """
        total_requests = len(events)
        if total_requests == 0:
            return TrafficTelemetryInput(
                total_requests=0,
                total_rps=0.0,
                baseline_rps=baseline_rps or 50.0,
                status_codes=StatusCodeDistribution(status_2xx=0, status_3xx=0, status_4xx=0, status_5xx=0),
                top_ip_ratio=0.0,
                unique_ip_count=0,
                non_standard_ua_ratio=0.0,
                single_endpoint_ratio=0.0,
            )

        effective_window = max(1, window_seconds)
        total_rps = round(total_requests / float(effective_window), 2)

        # 1. Status code distribution
        s_2xx, s_3xx, s_4xx, s_5xx = 0, 0, 0, 0
        for ev in events:
            if 200 <= ev.status_code < 300:
                s_2xx += 1
            elif 300 <= ev.status_code < 400:
                s_3xx += 1
            elif 400 <= ev.status_code < 500:
                s_4xx += 1
            elif 500 <= ev.status_code < 600:
                s_5xx += 1

        status_codes = StatusCodeDistribution(
            status_2xx=s_2xx,
            status_3xx=s_3xx,
            status_4xx=s_4xx,
            status_5xx=s_5xx,
        )

        # 2. IP concentration
        ip_counts = Counter(ev.client_ip for ev in events)
        top_ip_count = ip_counts.most_common(1)[0][1] if ip_counts else 0
        top_ip_ratio = round(top_ip_count / float(total_requests), 4)
        unique_ip_count = len(ip_counts)

        # 3. User-Agent anomaly ratio
        bot_ua_count = sum(1 for ev in events if cls.is_bot_user_agent(ev.user_agent))
        non_standard_ua_ratio = round(bot_ua_count / float(total_requests), 4)

        # 4. Single endpoint concentration
        endpoint_counts = Counter(ev.path.split("?")[0] for ev in events)
        top_endpoint_count = endpoint_counts.most_common(1)[0][1] if endpoint_counts else 0
        single_endpoint_ratio = round(top_endpoint_count / float(total_requests), 4)

        return TrafficTelemetryInput(
            total_requests=total_requests,
            total_rps=total_rps,
            baseline_rps=baseline_rps,
            status_codes=status_codes,
            top_ip_ratio=top_ip_ratio,
            unique_ip_count=unique_ip_count,
            non_standard_ua_ratio=non_standard_ua_ratio,
            single_endpoint_ratio=single_endpoint_ratio,
        )

