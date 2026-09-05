"""
SentinelScale — Traffic Harness Models
Defines typed scenarios, endpoint configurations, and observed request events.
"""
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TrafficScenarioType(str, Enum):
    """Canonical scenario types for traffic evaluation."""
    STEADY_LEGITIMATE = "steady_legitimate"
    LEGITIMATE_FLASH_CROWD = "legitimate_flash_crowd"
    HOSTILE_L7_FLOOD = "hostile_l7_flood"
    MIXED_TRAFFIC = "mixed_traffic"


class EndpointTarget(BaseModel):
    """Specification of an API endpoint to target during generation."""
    method: str = Field(default="GET", description="HTTP method (GET, POST, etc.)")
    path: str = Field(..., description="Target endpoint path, e.g. /products or /login")
    body: Optional[Dict[str, Any]] = Field(default=None, description="Optional JSON request body")
    weight: float = Field(default=1.0, ge=0.0, description="Relative selection weight")


class ObservedRequestEvent(BaseModel):
    """
    Granular measurement of an actual HTTP request dispatched by the harness.
    Forms the raw empirical foundation for telemetry aggregation.
    """
    timestamp: float = Field(..., description="Unix epoch timestamp in seconds when request occurred")
    method: str = Field(..., description="HTTP method dispatched")
    path: str = Field(..., description="Target endpoint path")
    status_code: int = Field(..., description="HTTP status code received")
    client_ip: str = Field(..., description="Client IP sent in X-Forwarded-For")
    user_agent: str = Field(..., description="User-Agent string sent with request")
    latency_ms: float = Field(..., ge=0.0, description="Observed round-trip latency in milliseconds")


class ScenarioDefinition(BaseModel):
    """
    Full specification of a traffic generation scenario.
    Controls only the traffic properties dispatched; does NOT determine assessment results.
    """
    name: str = Field(..., description="Human-readable scenario name")
    scenario_type: TrafficScenarioType = Field(..., description="Canonical scenario category")
    duration_seconds: float = Field(default=10.0, gt=0.0, description="Scenario duration in seconds")
    target_rps: float = Field(default=50.0, gt=0.0, description="Target request dispatch rate per second")
    baseline_rps: float = Field(default=50.0, gt=0.0, description="Expected nominal baseline RPS for burst detection")
    client_ips: List[str] = Field(..., min_length=1, description="Pool of client IPs to sample from")
    ip_weights: Optional[List[float]] = Field(default=None, description="Optional sampling weights for client IPs")
    user_agents: List[str] = Field(..., min_length=1, description="Pool of User-Agents to sample from")
    ua_weights: Optional[List[float]] = Field(default=None, description="Optional sampling weights for User-Agents")
    endpoints: List[EndpointTarget] = Field(..., min_length=1, description="Endpoints to dispatch traffic against")
    trace_id: Optional[str] = Field(default=None, description="Optional distributed trace ID for correlation")


# Canonical User-Agent pools
BROWSER_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36",
]

BOT_USER_AGENTS = [
    "curl/7.88.1",
    "python-requests/2.31.0",
    "Go-http-client/1.1",
    "Scrapy/2.11.0 (+https://scrapy.org)",
    "Apache-HttpClient/4.5.13 (Java/17.0.2)",
    "",
]


def create_scenario_preset(scenario_type: TrafficScenarioType, duration_seconds: float = 10.0) -> ScenarioDefinition:
    """Factory creating canonical scenario definitions for test and live evaluation."""
    # Standard realistic endpoint catalog
    standard_endpoints = [
        EndpointTarget(method="GET", path="/products", weight=4.0),
        EndpointTarget(method="GET", path="/products/prod-001", weight=3.0),
        EndpointTarget(method="GET", path="/products/prod-002", weight=2.0),
        EndpointTarget(method="GET", path="/search?q=security", weight=2.0),
        EndpointTarget(method="POST", path="/cart", body={"user_id": "u-123", "items": [{"product_id": "prod-001", "quantity": 1}]}, weight=1.0),
    ]

    if scenario_type == TrafficScenarioType.STEADY_LEGITIMATE:
        # 50 distributed client IPs, organic browser UAs, baseline RPS
        diverse_ips = [f"198.51.100.{i}" for i in range(1, 51)]
        return ScenarioDefinition(
            name="Steady Legitimate Traffic",
            scenario_type=TrafficScenarioType.STEADY_LEGITIMATE,
            duration_seconds=duration_seconds,
            target_rps=50.0,
            baseline_rps=50.0,
            client_ips=diverse_ips,
            user_agents=BROWSER_USER_AGENTS,
            endpoints=standard_endpoints,
        )

    elif scenario_type == TrafficScenarioType.LEGITIMATE_FLASH_CROWD:
        # 100 distributed client IPs, organic browser UAs, 5x surge above baseline
        diverse_ips = [f"203.0.113.{i}" for i in range(1, 101)]
        return ScenarioDefinition(
            name="Legitimate Flash Crowd Surge",
            scenario_type=TrafficScenarioType.LEGITIMATE_FLASH_CROWD,
            duration_seconds=duration_seconds,
            target_rps=250.0,
            baseline_rps=50.0,
            client_ips=diverse_ips,
            user_agents=BROWSER_USER_AGENTS,
            endpoints=standard_endpoints,
        )

    elif scenario_type == TrafficScenarioType.HOSTILE_L7_FLOOD:
        # Concentrated single attacker IP (90% weight), bot user-agents, high 4xx/5xx endpoint errors
        hostile_ips = ["192.0.2.99", "192.0.2.100", "192.0.2.101"]
        hostile_weights = [0.90, 0.05, 0.05]
        hostile_endpoints = [
            EndpointTarget(method="GET", path="/products/invalid-nonexistent-id", weight=5.0),
            EndpointTarget(method="POST", path="/login", body={"username": "", "password": ""}, weight=4.0),
            EndpointTarget(method="GET", path="/products", weight=1.0),
        ]
        return ScenarioDefinition(
            name="Hostile L7 Flood Attack",
            scenario_type=TrafficScenarioType.HOSTILE_L7_FLOOD,
            duration_seconds=duration_seconds,
            target_rps=300.0,
            baseline_rps=50.0,
            client_ips=hostile_ips,
            ip_weights=hostile_weights,
            user_agents=BOT_USER_AGENTS,
            endpoints=hostile_endpoints,
        )

    elif scenario_type == TrafficScenarioType.MIXED_TRAFFIC:
        # Blended: 30 legitimate distributed IPs with browsers + 1 concentrated scraper IP with curl
        all_ips = [f"198.51.100.{i}" for i in range(1, 31)] + ["192.0.2.66"]
        # The single scraper accounts for ~40% of requests
        weights = [0.60 / 30] * 30 + [0.40]
        mixed_uas = BROWSER_USER_AGENTS + BOT_USER_AGENTS
        mixed_ua_weights = [0.60 / len(BROWSER_USER_AGENTS)] * len(BROWSER_USER_AGENTS) + [0.40 / len(BOT_USER_AGENTS)] * len(BOT_USER_AGENTS)
        mixed_endpoints = standard_endpoints + [
            EndpointTarget(method="GET", path="/products/invalid-crawler-probe", weight=2.0)
        ]
        return ScenarioDefinition(
            name="Mixed Legitimate and Scraper Traffic",
            scenario_type=TrafficScenarioType.MIXED_TRAFFIC,
            duration_seconds=duration_seconds,
            target_rps=150.0,
            baseline_rps=75.0,
            client_ips=all_ips,
            ip_weights=weights,
            user_agents=mixed_uas,
            ua_weights=mixed_ua_weights,
            endpoints=mixed_endpoints,
        )

    raise ValueError(f"Unknown scenario type: {scenario_type}")

