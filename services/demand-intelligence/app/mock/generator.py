import uuid
from datetime import datetime, timezone
from app.config.settings import settings
from app.models.demand import DemandForecast


class MockDemandDataGenerator:
    """
    Deterministic Mock Generator for Demand Intelligence (demand-v0).
    Isolated mock layer predicting future legitimate demand independently
    of synchronous traffic intelligence calls.
    """

    @staticmethod
    def generate_forecast(
        forecast_horizon_seconds: int = 300,
        trace_id: str | None = None
    ) -> DemandForecast:
        trace = trace_id or f"trace-{uuid.uuid4().hex[:16]}"
        return DemandForecast(
            event_id=str(uuid.uuid4()),
            trace_id=trace,
            generated_at=datetime.now(timezone.utc).isoformat(),
            contract_version=settings.CONTRACT_VERSION,
            service_version=settings.SERVICE_VERSION,
            model_version=f"{settings.MODEL_VERSION} (mock)",
            forecast_horizon_seconds=forecast_horizon_seconds,
            predicted_legitimate_rps=1200.0,
            lower_bound_rps=1050.0,
            upper_bound_rps=1400.0,
            confidence=0.91
        )
