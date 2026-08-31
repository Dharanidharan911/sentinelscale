from app.mock.generator import MockTrafficDataGenerator
from app.models.traffic import AssessmentRequest, TrafficAssessment


class TrafficAssessmentService:
    """
    Traffic Intelligence service layer.
    Coordinates telemetry assessment and feature extraction.
    Currently backed by the isolated mock generator (traffic-v0).
    """

    def __init__(self):
        self.mock_generator = MockTrafficDataGenerator()

    async def assess_traffic(self, request: AssessmentRequest) -> TrafficAssessment:
        # Deterministic contract-compliant mock implementation (traffic-v0)
        return self.mock_generator.generate_assessment(
            window_seconds=request.window_seconds,
            trace_id=request.trace_id
        )
