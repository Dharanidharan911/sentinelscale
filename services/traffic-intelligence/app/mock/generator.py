import uuid
from datetime import datetime, timezone
from app.config.settings import settings
from app.models.traffic import TrafficAssessment, TrafficClassification


class MockTrafficDataGenerator:
    """
    Deterministic Mock Generator for Traffic Intelligence (traffic-v0).
    Isolated mock layer providing contract-compliant baseline payloads
    prior to real ML model integration.
    """

    @staticmethod
    def generate_assessment(
        window_seconds: int = 60,
        trace_id: str | None = None
    ) -> TrafficAssessment:
        trace = trace_id or f"trace-{uuid.uuid4().hex[:16]}"
        return TrafficAssessment(
            event_id=str(uuid.uuid4()),
            trace_id=trace,
            timestamp=datetime.now(timezone.utc).isoformat(),
            contract_version=settings.CONTRACT_VERSION,
            service_version=settings.SERVICE_VERSION,
            model_version=f"{settings.MODEL_VERSION} (mock)",
            window_seconds=window_seconds,
            total_rps=2500.0,
            legitimate_rps_estimate=850.0,
            suspicious_rps_estimate=1650.0,
            risk_score=0.84,
            legitimacy_score=0.34,
            confidence=0.91,
            classification=TrafficClassification.SUSPICIOUS,
            top_signals=[
                "high_burst_rate",
                "client_ip_concentration",
                "non_standard_user_agent"
            ]
        )
