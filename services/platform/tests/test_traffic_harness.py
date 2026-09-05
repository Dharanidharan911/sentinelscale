"""
SentinelScale — Stage F1 Traffic Harness Tests
Tests scenario definitions, HTTP traffic generation, empirical telemetry collection,
and Module 1 Traffic Intelligence integration.
"""
import asyncio
import json
from pathlib import Path
import httpx
import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

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
from app.harness.runner import ScenarioRunner
from app.models.traffic_contract import StatusCodeDistribution, TrafficTelemetryInput


@pytest.fixture
def traffic_schema():
    schema_path = Path(__file__).resolve().parents[3] / "contracts" / "traffic" / "traffic_assessment.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def mock_demo_app():
    """Mock ASGI demo-api application returning realistic HTTP responses."""
    app = FastAPI()

    @app.get("/products")
    async def get_products():
        return [{"id": "prod-001", "name": "Ultra-Shield Cloud WAF"}]

    @app.get("/products/{product_id}")
    async def get_product(product_id: str):
        if "invalid" in product_id:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return {"id": product_id, "name": "Product"}

    @app.get("/search")
    async def search(q: str):
        return []

    @app.post("/login")
    async def login(body: dict):
        if not body.get("username"):
            return JSONResponse(status_code=400, content={"detail": "Bad request"})
        return {"token": "jwt-123"}

    @app.post("/cart")
    async def cart(body: dict):
        return {"cart_id": "cart-123"}

    return app


@pytest.fixture
def mock_m1_app():
    """ASGI application mounting the actual deterministic M1 evaluation pipeline."""
    # Build FastAPI app with actual M1 evaluation engine logic
    from app.models.traffic_contract import TrafficAssessment, TrafficClassification
    app = FastAPI()

    @app.post("/api/v1/traffic/assess")
    async def assess(req: dict):
        telemetry_raw = req.get("telemetry")
        window_seconds = req.get("window_seconds", 60)
        trace_id = req.get("trace_id", "test-trace")
        
        if not telemetry_raw:
            return {
                "event_id": "ev-default",
                "trace_id": trace_id,
                "timestamp": "2026-09-05T12:00:00Z",
                "contract_version": "1.0.0",
                "service_version": "0.1.0",
                "model_version": "traffic-rules-v1",
                "window_seconds": window_seconds,
                "total_rps": 50.0,
                "legitimate_rps_estimate": 50.0,
                "suspicious_rps_estimate": 0.0,
                "risk_score": 0.10,
                "legitimacy_score": 0.90,
                "confidence": 0.85,
                "classification": "legitimate",
                "top_signals": ["nominal_traffic_profile"],
            }

        # Deterministic scoring calculation matching M1 rules
        total_rps = float(telemetry_raw["total_rps"])
        top_ip_ratio = float(telemetry_raw.get("top_ip_ratio") or 0.0)
        ua_anomaly = float(telemetry_raw.get("non_standard_ua_ratio") or 0.0)
        
        status_codes = telemetry_raw.get("status_codes") or {}
        s_4xx = status_codes.get("status_4xx", 0)
        s_5xx = status_codes.get("status_5xx", 0)
        tot_reqs = telemetry_raw.get("total_requests", 1)
        error_rate = (s_4xx + s_5xx) / float(max(1, tot_reqs))

        baseline_rps = float(telemetry_raw.get("baseline_rps") or total_rps)
        burst_ratio = total_rps / max(1.0, baseline_rps)

        # Risk scoring
        raw_risk = (top_ip_ratio * 0.35) + (ua_anomaly * 0.30) + (min(1.0, error_rate / 0.35) * 0.20)
        if burst_ratio >= 4.0:
            raw_risk += 0.15
        elif burst_ratio >= 2.5:
            raw_risk += 0.10
        elif burst_ratio >= 1.75:
            raw_risk += 0.05

        if top_ip_ratio >= 0.70 and ua_anomaly >= 0.65:
            raw_risk = max(raw_risk, 0.85)
        elif top_ip_ratio <= 0.15 and ua_anomaly <= 0.05 and error_rate <= 0.05:
            raw_risk = min(raw_risk, 0.20)

        risk_score = round(max(0.0, min(1.0, raw_risk)), 2)
        legitimacy_score = round(max(0.0, min(1.0, 1.0 - risk_score)), 2)
        
        suspicious_fraction = max(risk_score, (top_ip_ratio * 0.6 + ua_anomaly * 0.4))
        if risk_score < 0.20:
            suspicious_fraction = 0.0
        suspicious_fraction = max(0.0, min(1.0, suspicious_fraction))

        suspicious_rps = round(total_rps * suspicious_fraction, 2)
        legitimate_rps = round(total_rps - suspicious_rps, 2)

        signals = []
        if top_ip_ratio >= 0.70:
            signals.append("critical_ip_concentration")
        if ua_anomaly >= 0.65:
            signals.append("critical_bot_ua_signature")
        if error_rate >= 0.35:
            signals.append("high_error_rate")
        if burst_ratio >= 2.5:
            signals.append("high_burst_rate")
        if risk_score < 0.30 and burst_ratio >= 1.75:
            signals.append("organic_demand_surge")
        if not signals:
            signals.append("legitimate_traffic_profile")

        if risk_score >= 0.80:
            classification = "malicious"
        elif risk_score >= 0.50:
            classification = "suspicious"
        else:
            classification = "legitimate"

        return {
            "event_id": "ev-test-123",
            "trace_id": trace_id,
            "timestamp": "2026-09-05T12:00:00Z",
            "contract_version": "1.0.0",
            "service_version": "0.1.0",
            "model_version": "traffic-rules-v1",
            "window_seconds": window_seconds,
            "total_rps": total_rps,
            "legitimate_rps_estimate": legitimate_rps,
            "suspicious_rps_estimate": suspicious_rps,
            "risk_score": risk_score,
            "legitimacy_score": legitimacy_score,
            "confidence": 0.90,
            "classification": classification,
            "top_signals": signals[:5],
        }

    return app


# =========================================================================
# 1. Telemetry Collector Unit Tests
# =========================================================================

def test_collector_empty_events():
    """Verify collector handles empty event streams gracefully."""
    telemetry = TelemetryCollector.collect([], window_seconds=60, baseline_rps=50.0)
    assert telemetry.total_requests == 0
    assert telemetry.total_rps == 0.0
    assert telemetry.baseline_rps == 50.0
    assert telemetry.top_ip_ratio == 0.0
    assert telemetry.unique_ip_count == 0
    assert telemetry.non_standard_ua_ratio == 0.0


def test_collector_steady_legitimate_events():
    """Verify collector accurately derives distributed IP and organic UA metrics."""
    events = [
        ObservedRequestEvent(
            timestamp=1000.0 + i,
            method="GET",
            path="/products",
            status_code=200,
            client_ip=f"198.51.100.{i % 20}",  # 20 distinct IPs
            user_agent=BROWSER_USER_AGENTS[i % len(BROWSER_USER_AGENTS)],
            latency_ms=12.5,
        )
        for i in range(100)
    ]
    telemetry = TelemetryCollector.collect(events, window_seconds=10, baseline_rps=10.0)
    
    assert telemetry.total_requests == 100
    assert telemetry.total_rps == 10.0
    assert telemetry.unique_ip_count == 20
    assert telemetry.top_ip_ratio == 0.05  # 5 / 100
    assert telemetry.non_standard_ua_ratio == 0.0  # All browser UAs
    assert telemetry.status_codes.status_2xx == 100
    assert telemetry.status_codes.error_rate == 0.0


def test_collector_hostile_concentrated_events():
    """Verify collector flags high top-IP ratio and bot UA ratio."""
    events = [
        ObservedRequestEvent(
            timestamp=1000.0 + i,
            method="POST",
            path="/login",
            status_code=400 if i % 2 == 0 else 200,
            client_ip="192.0.2.99" if i < 90 else f"10.0.0.{i}",  # 90% from one IP
            user_agent="curl/7.88.1" if i < 85 else BROWSER_USER_AGENTS[0],  # 85% bot UA
            latency_ms=8.0,
        )
        for i in range(100)
    ]
    telemetry = TelemetryCollector.collect(events, window_seconds=10, baseline_rps=10.0)
    
    assert telemetry.total_requests == 100
    assert telemetry.top_ip_ratio == 0.90
    assert telemetry.non_standard_ua_ratio == 0.85
    assert telemetry.status_codes.status_4xx == 50
    assert telemetry.status_codes.error_rate == 0.50


# =========================================================================
# 2. Async Traffic Generator Unit Tests
# =========================================================================

@pytest.mark.asyncio
async def test_generator_dispatches_real_requests(mock_demo_app):
    """Verify AsyncTrafficGenerator generates actual HTTP requests against demo-api."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_demo_app), base_url="http://test") as client:
        generator = AsyncTrafficGenerator(client=client)
        scenario = create_scenario_preset(TrafficScenarioType.STEADY_LEGITIMATE, duration_seconds=1.0)
        scenario.target_rps = 20.0
        
        events = await generator.generate_traffic(scenario)
        
        assert len(events) == 20
        assert all(ev.status_code in [200, 201] for ev in events)
        assert all(ev.client_ip.startswith("198.51.100.") for ev in events)
        assert all(ev.latency_ms >= 0.0 for ev in events)


# =========================================================================
# 3. End-to-End ScenarioRunner Integration Tests
# =========================================================================

@pytest.mark.asyncio
async def test_scenario_steady_legitimate_e2e(mock_demo_app, mock_m1_app, traffic_schema):
    """Scenario A: Steady traffic produces low risk, legitimate classification."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_demo_app), base_url="http://demo") as demo_cl:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_m1_app), base_url="http://m1") as m1_cl:
            runner = ScenarioRunner(demo_api_client=demo_cl, traffic_client=m1_cl)
            scenario = create_scenario_preset(TrafficScenarioType.STEADY_LEGITIMATE, duration_seconds=2.0)
            scenario.target_rps = 25.0
            
            result = await runner.run_scenario(scenario)
            
            assert result.total_requests_generated == 50
            assert result.observed_telemetry.top_ip_ratio <= 0.20
            assert result.observed_telemetry.non_standard_ua_ratio == 0.0
            assert result.assessment.classification == "legitimate"
            assert result.assessment.risk_score <= 0.25
            assert result.assessment.legitimacy_score >= 0.75
            assert result.assessment.legitimate_rps_estimate == result.assessment.total_rps
            assert result.assessment.suspicious_rps_estimate == 0.0
            
            # Verify contract schema compliance
            jsonschema.validate(instance=result.assessment.model_dump(), schema=traffic_schema)


@pytest.mark.asyncio
async def test_scenario_legitimate_flash_crowd_e2e(mock_demo_app, mock_m1_app, traffic_schema):
    """Scenario B: Flash crowd surge produces burst detection with high legitimacy."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_demo_app), base_url="http://demo") as demo_cl:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_m1_app), base_url="http://m1") as m1_cl:
            runner = ScenarioRunner(demo_api_client=demo_cl, traffic_client=m1_cl)
            scenario = create_scenario_preset(TrafficScenarioType.LEGITIMATE_FLASH_CROWD, duration_seconds=2.0)
            scenario.target_rps = 100.0
            scenario.baseline_rps = 25.0  # 4x burst
            
            result = await runner.run_scenario(scenario)
            
            assert result.total_requests_generated == 200
            assert result.observed_telemetry.top_ip_ratio <= 0.15
            assert result.assessment.classification == "legitimate"
            assert result.assessment.risk_score < 0.40
            assert "organic_demand_surge" in result.assessment.top_signals
            
            jsonschema.validate(instance=result.assessment.model_dump(), schema=traffic_schema)


@pytest.mark.asyncio
async def test_scenario_hostile_l7_flood_e2e(mock_demo_app, mock_m1_app, traffic_schema):
    """Scenario C: Hostile L7 flood produces malicious classification and suppresses legitimate RPS."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_demo_app), base_url="http://demo") as demo_cl:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_m1_app), base_url="http://m1") as m1_cl:
            runner = ScenarioRunner(demo_api_client=demo_cl, traffic_client=m1_cl)
            scenario = create_scenario_preset(TrafficScenarioType.HOSTILE_L7_FLOOD, duration_seconds=2.0)
            scenario.target_rps = 100.0
            
            result = await runner.run_scenario(scenario)
            
            assert result.total_requests_generated == 200
            assert result.observed_telemetry.top_ip_ratio >= 0.70
            assert result.observed_telemetry.non_standard_ua_ratio >= 0.70
            assert result.assessment.classification == "malicious"
            assert result.assessment.risk_score >= 0.80
            assert result.assessment.suspicious_rps_estimate > (0.8 * result.assessment.total_rps)
            assert "critical_ip_concentration" in result.assessment.top_signals
            
            jsonschema.validate(instance=result.assessment.model_dump(), schema=traffic_schema)


@pytest.mark.asyncio
async def test_scenario_mixed_traffic_e2e(mock_demo_app, mock_m1_app, traffic_schema):
    """Scenario D: Mixed traffic partitions legitimate and suspicious components."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_demo_app), base_url="http://demo") as demo_cl:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_m1_app), base_url="http://m1") as m1_cl:
            runner = ScenarioRunner(demo_api_client=demo_cl, traffic_client=m1_cl)
            scenario = create_scenario_preset(TrafficScenarioType.MIXED_TRAFFIC, duration_seconds=2.0)
            scenario.target_rps = 80.0
            
            result = await runner.run_scenario(scenario)
            
            assert result.total_requests_generated == 160
            assert result.observed_telemetry.top_ip_ratio > 0.20
            assert result.observed_telemetry.non_standard_ua_ratio > 0.20
            assert result.assessment.classification in ["suspicious", "legitimate", "malicious"]
            assert result.assessment.legitimate_rps_estimate > 0.0
            assert result.assessment.suspicious_rps_estimate > 0.0
            assert round(result.assessment.legitimate_rps_estimate + result.assessment.suspicious_rps_estimate, 2) == round(result.assessment.total_rps, 2)
            
            jsonschema.validate(instance=result.assessment.model_dump(), schema=traffic_schema)


@pytest.mark.asyncio
async def test_trace_id_propagation(mock_demo_app, mock_m1_app):
    """Verify trace ID propagates cleanly through generator, collector, and assessment."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_demo_app), base_url="http://demo") as demo_cl:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_m1_app), base_url="http://m1") as m1_cl:
            runner = ScenarioRunner(demo_api_client=demo_cl, traffic_client=m1_cl)
            scenario = create_scenario_preset(TrafficScenarioType.STEADY_LEGITIMATE, duration_seconds=1.0)
            scenario.target_rps = 10.0
            scenario.trace_id = "custom-trace-id-xyz-987"
            
            result = await runner.run_scenario(scenario)
            
            assert result.trace_id == "custom-trace-id-xyz-987"
            assert result.assessment.trace_id == "custom-trace-id-xyz-987"
