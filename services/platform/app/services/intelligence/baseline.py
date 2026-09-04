import math
import statistics
from typing import Dict, List, Optional
from app.models.anomaly import MetricBaseline
from app.models.history import StoredObservation


class BehavioralBaselineService:
    """
    Computes deterministic historical reference baselines across key telemetry,
    demand, and scaling decision metrics using the standard Python library.
    """

    @staticmethod
    def calculate_metric_baseline(metric_name: str, values: List[float]) -> Optional[MetricBaseline]:
        """
        Calculate population mean, standard deviation, min, max, and median for a list of values.
        Returns None if values list is empty.
        """
        if not values:
            return None

        n = len(values)
        mean_val = sum(values) / n
        # Population standard deviation: sqrt(sum((x - mean)^2) / N)
        variance = sum((x - mean_val) ** 2 for x in values) / n
        stddev_val = math.sqrt(variance)
        min_val = min(values)
        max_val = max(values)
        med_val = statistics.median(values)

        return MetricBaseline(
            metric=metric_name,
            sample_count=n,
            mean=round(mean_val, 4),
            stddev=round(stddev_val, 4),
            min_value=round(min_val, 4),
            max_value=round(max_val, 4),
            median=round(med_val, 4),
        )

    def extract_baselines_from_observations(
        self,
        observations: List[StoredObservation]
    ) -> Dict[str, MetricBaseline]:
        """
        Extract per-metric baseline statistics from a sequence of StoredObservation records.
        """
        successful_obs = [o for o in observations if o.success]
        if not successful_obs:
            return {}

        metrics_data: Dict[str, List[float]] = {
            "predicted_legitimate_rps": [],
            "traffic_risk": [],
            "current_capacity_rps": [],
            "recommended_pods": [],
            "current_pods": [],
            "baseline_hpa_recommended_pods": [],
            "pod_delta_vs_baseline": [],
        }

        for o in successful_obs:
            if o.predicted_legitimate_rps is not None:
                metrics_data["predicted_legitimate_rps"].append(float(o.predicted_legitimate_rps))
            if o.traffic_risk is not None:
                metrics_data["traffic_risk"].append(float(o.traffic_risk))
            if o.current_capacity_rps is not None:
                metrics_data["current_capacity_rps"].append(float(o.current_capacity_rps))
            if o.recommended_pods is not None:
                metrics_data["recommended_pods"].append(float(o.recommended_pods))
            if o.current_pods is not None:
                metrics_data["current_pods"].append(float(o.current_pods))
            if o.baseline_hpa_recommended_pods is not None:
                metrics_data["baseline_hpa_recommended_pods"].append(float(o.baseline_hpa_recommended_pods))
            if o.pod_delta_vs_baseline is not None:
                metrics_data["pod_delta_vs_baseline"].append(float(o.pod_delta_vs_baseline))

        baselines: Dict[str, MetricBaseline] = {}
        for m_name, vals in metrics_data.items():
            b = self.calculate_metric_baseline(m_name, vals)
            if b is not None:
                baselines[m_name] = b

        return baselines

