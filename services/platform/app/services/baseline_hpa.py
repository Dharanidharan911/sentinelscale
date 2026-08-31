import math
from app.config.settings import settings
from app.models.resource import ResourceState


class BaselineHPACalculator:
    """
    Standard Reactive Kubernetes Horizontal Pod Autoscaler (HPA) Baseline Calculator.
    Calculates what a traditional metrics-server/HPA controller would recommend
    based on raw total utilization/traffic, without security context.

    Formula:
        desiredReplicas = ceil[currentReplicas * (currentMetricValue / targetMetricValue)]
    """

    def __init__(
        self,
        target_cpu_utilization: float | None = None,
        min_pods: int | None = None,
        max_pods: int | None = None
    ):
        self.target_cpu_utilization = target_cpu_utilization or settings.DEFAULT_TARGET_CPU_UTILIZATION
        self.min_pods = min_pods or settings.DEFAULT_MIN_PODS
        self.max_pods = max_pods or settings.DEFAULT_MAX_PODS

    def calculate_baseline_replicas(
        self,
        resource_state: ResourceState,
        target_cpu: float | None = None
    ) -> int:
        target = target_cpu or self.target_cpu_utilization
        current_pods = max(1, resource_state.running_pods)
        current_cpu = max(0.01, resource_state.cpu_utilization)

        # Standard HPA replica calculation ratio
        raw_desired = math.ceil(current_pods * (current_cpu / target))

        # Clamp between configured HPA min and max pods
        bounded_replicas = max(self.min_pods, min(raw_desired, self.max_pods))
        return bounded_replicas
