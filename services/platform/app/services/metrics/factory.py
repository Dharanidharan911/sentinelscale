from typing import Optional
from app.services.metrics.base import MetricsCollector
from app.services.metrics.prometheus import PrometheusMetricsService

_global_metrics: Optional[PrometheusMetricsService] = None


def get_metrics_service() -> PrometheusMetricsService:
    """
    Factory function returning the singleton PrometheusMetricsService instance.
    """
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = PrometheusMetricsService()
    return _global_metrics

