"""
SentinelScale — Traffic Harness Package
Provides scenario definitions, async HTTP traffic generation, empirical telemetry collection,
and Module 1 assessment orchestration for Stage F1.
"""
from app.harness.collector import TelemetryCollector
from app.harness.generator import AsyncTrafficGenerator
from app.harness.models import (
    EndpointTarget,
    ObservedRequestEvent,
    ScenarioDefinition,
    TrafficScenarioType,
    create_scenario_preset,
    BROWSER_USER_AGENTS,
    BOT_USER_AGENTS,
)
from app.harness.runner import ScenarioExecutionResult, ScenarioRunner

__all__ = [
    "TelemetryCollector",
    "AsyncTrafficGenerator",
    "EndpointTarget",
    "ObservedRequestEvent",
    "ScenarioDefinition",
    "TrafficScenarioType",
    "create_scenario_preset",
    "BROWSER_USER_AGENTS",
    "BOT_USER_AGENTS",
    "ScenarioExecutionResult",
    "ScenarioRunner",
]

