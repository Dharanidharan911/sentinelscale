from app.mock.generator import MockTrafficDataGenerator
from app.models.traffic import AssessmentRequest, TrafficAssessment
from app.pipeline.engine import TrafficIntelligenceEngine


class TrafficAssessmentService:
    """
    Traffic Intelligence service layer.
    Coordinates telemetry assessment and feature extraction through the
    deterministic intelligence pipeline (traffic-rules-v1), with isolated mock fallback.
    """

    def __init__(self):
        self.engine = TrafficIntelligenceEngine()
        self.mock_generator = MockTrafficDataGenerator()

    async def assess_traffic(self, request: AssessmentRequest) -> TrafficAssessment:
        # Execute the deterministic intelligence pipeline
        return self.engine.evaluate(request)
