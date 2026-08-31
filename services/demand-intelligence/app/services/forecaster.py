from app.mock.generator import MockDemandDataGenerator
from app.models.demand import DemandForecast, ForecastRequest


class DemandForecastingService:
    """
    Demand Intelligence service layer.
    Extracts time-series demand patterns and estimates future workload.
    Operates independently and asynchronously.
    """

    def __init__(self):
        self.mock_generator = MockDemandDataGenerator()

    async def forecast_demand(self, request: ForecastRequest) -> DemandForecast:
        return self.mock_generator.generate_forecast(
            forecast_horizon_seconds=request.forecast_horizon_seconds,
            trace_id=request.trace_id
        )
