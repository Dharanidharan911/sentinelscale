import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from app.models.decision import ScalingAction, ScalingDecision
from app.services.metrics.base import MetricsCollector

# Standard Prometheus latency histogram buckets for API/evaluation latency
LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def normalize_reason(reason: Optional[str]) -> str:
    """Normalize free-form decision reason into bounded low-cardinality category."""
    if not reason:
        return "OTHER"
    r = reason.lower()
    if "clamp" in r or "guardrail" in r or "step-up" in r or "limit" in r:
        return "POLICY_CLAMPED"
    if "attack" in r or "malicious" in r or "hold" in r or "suppress" in r:
        return "ATTACK_MITIGATION"
    if "surge" in r or "scale up" in r or "legitimate" in r:
        return "LEGITIMATE_DEMAND_SURGE"
    if "scale down" in r or "low demand" in r or "underutilized" in r:
        return "DEMAND_SCALE_DOWN"
    if "capacity" in r or "sufficient" in r:
        return "CAPACITY_SUFFICIENT"
    return "OTHER"


def normalize_error(error_type: Optional[str], error_message: Optional[str] = None) -> str:
    """Normalize arbitrary error strings into bounded low-cardinality error categories."""
    combined = f"{error_type or ''} {error_message or ''}".lower()
    if "timeout" in combined or "timed out" in combined:
        return "timeout"
    if "502" in combined or "bad gateway" in combined:
        return "bad_gateway"
    if "connection" in combined or "refused" in combined or "connect" in combined:
        return "connection_error"
    if "schema" in combined or "validation" in combined or "contract" in combined:
        return "schema_validation"
    if "telemetry" in combined:
        return "telemetry_error"
    if "500" in combined or "internal" in combined:
        return "internal_error"
    return "unknown"


class PrometheusMetricsService(MetricsCollector):
    """
    Pure-Python Prometheus metrics collector and exposition formatter.
    Thread-safe, zero external dependencies, strictly low-cardinality labels,
    and isolated for reproducible unit testing.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        """Reset all metrics state (useful for test isolation)."""
        with getattr(self, "_lock", threading.Lock()):
            # Counters: map (metric_name, tuple_of_labels) -> float
            self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)

            # Gauges: map (metric_name, tuple_of_labels) -> float
            self._gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}

            # Histograms: map metric_name -> { "buckets": Dict[float, int], "sum": float, "count": int }
            self._histograms: Dict[str, Dict] = {
                "sentinelscale_evaluation_duration_seconds": {
                    "buckets": {b: 0 for b in LATENCY_BUCKETS},
                    "sum": 0.0,
                    "count": 0,
                }
            }

            # Initialize base counters to zero
            self._counters[("sentinelscale_observations_total", (("status", "success"),))] = 0.0
            self._counters[("sentinelscale_observations_total", (("status", "failure"),))] = 0.0
            self._counters[("sentinelscale_scheduler_observations_skipped_total", ())] = 0.0
            self._counters[("sentinelscale_history_write_failures_total", ())] = 0.0
            self._counters[("sentinelscale_history_cleanup_total", ())] = 0.0

            # Initialize base gauges
            self._gauges[("sentinelscale_scheduler_running", ())] = 0.0
            self._gauges[("sentinelscale_scheduler_last_success_timestamp_seconds", ())] = 0.0
            self._gauges[("sentinelscale_scheduler_last_failure_timestamp_seconds", ())] = 0.0

    def record_observation_success(self, decision: ScalingDecision, duration_s: float) -> None:
        with self._lock:
            # 1. Observation counter
            self._counters[("sentinelscale_observations_total", (("status", "success"),))] += 1.0

            # 2. Decision counter
            action_label = decision.action.value if hasattr(decision.action, "value") else str(decision.action)
            self._counters[("sentinelscale_decisions_total", (("action", action_label),))] += 1.0

            # 3. Decision reason category counter
            reason_cat = normalize_reason(decision.reason)
            self._counters[("sentinelscale_decision_reasons_total", (("reason_category", reason_cat),))] += 1.0

            # 4. Latency histogram
            hist = self._histograms["sentinelscale_evaluation_duration_seconds"]
            hist["count"] += 1
            hist["sum"] += duration_s
            for b in LATENCY_BUCKETS:
                if duration_s <= b:
                    hist["buckets"][b] += 1

            # 5. Baseline HPA vs SentinelScale Gauges
            self._gauges[("sentinelscale_sentinelscale_recommendation_pods", ())] = float(decision.recommended_pods)
            self._gauges[("sentinelscale_baseline_hpa_recommendation_pods", ())] = float(decision.baseline_hpa_recommended_pods)
            self._gauges[("sentinelscale_baseline_hpa_divergence_pods", ())] = float(decision.pod_delta_vs_baseline)

            # 6. Demand / Traffic Indicators
            self._gauges[("sentinelscale_traffic_risk", ())] = float(decision.traffic_risk)
            self._gauges[("sentinelscale_predicted_legitimate_rps", ())] = float(decision.predicted_legitimate_rps)
            self._gauges[("sentinelscale_current_capacity_rps", ())] = float(decision.current_capacity_rps)
            self._gauges[("sentinelscale_current_pods", ())] = float(decision.current_pods)
            self._gauges[("sentinelscale_recommended_pods", ())] = float(decision.recommended_pods)

            # 7. Scheduler timestamp
            self._gauges[("sentinelscale_scheduler_last_success_timestamp_seconds", ())] = time.time()

    def record_observation_failure(self, service: str, error_type: str, duration_s: float) -> None:
        with self._lock:
            # 1. Observation counter
            self._counters[("sentinelscale_observations_total", (("status", "failure"),))] += 1.0

            # 2. Upstream failure counter
            normalized_service = service.lower().replace(" ", "_")
            normalized_err = normalize_error(error_type)
            labels = (("error_type", normalized_err), ("service", normalized_service))
            self._counters[("sentinelscale_upstream_failures_total", labels)] += 1.0

            # 3. Latency histogram
            hist = self._histograms["sentinelscale_evaluation_duration_seconds"]
            hist["count"] += 1
            hist["sum"] += duration_s
            for b in LATENCY_BUCKETS:
                if duration_s <= b:
                    hist["buckets"][b] += 1

            # 4. Scheduler failure timestamp
            self._gauges[("sentinelscale_scheduler_last_failure_timestamp_seconds", ())] = time.time()

    def set_scheduler_running(self, running: bool) -> None:
        with self._lock:
            self._gauges[("sentinelscale_scheduler_running", ())] = 1.0 if running else 0.0

    def record_scheduler_skipped(self) -> None:
        with self._lock:
            self._counters[("sentinelscale_scheduler_observations_skipped_total", ())] += 1.0

    def record_history_write(self, success: bool) -> None:
        with self._lock:
            status = "success" if success else "failure"
            self._counters[("sentinelscale_history_records_total", (("status", status),))] += 1.0
            if not success:
                self._counters[("sentinelscale_history_write_failures_total", ())] += 1.0

    def record_history_cleanup(self, count: int) -> None:
        with self._lock:
            self._counters[("sentinelscale_history_cleanup_total", ())] += float(count)

    def export_prometheus_text(self) -> str:
        """Render all collected metrics into standard Prometheus exposition text format."""
        with self._lock:
            lines: List[str] = []

            # Metric documentation & type annotations
            metadata = {
                "sentinelscale_observations_total": ("counter", "Total count of evaluation cycles executed."),
                "sentinelscale_decisions_total": ("counter", "Total scaling decisions grouped by action."),
                "sentinelscale_decision_reasons_total": ("counter", "Total decisions categorized by normalized rationale."),
                "sentinelscale_upstream_failures_total": ("counter", "Total upstream intelligence or telemetry failures."),
                "sentinelscale_evaluation_duration_seconds": ("histogram", "End-to-end evaluation cycle execution duration."),
                "sentinelscale_sentinelscale_recommendation_pods": ("gauge", "SentinelScale recommended replicas for target workload."),
                "sentinelscale_baseline_hpa_recommendation_pods": ("gauge", "Reactive HPA recommended replicas for target workload."),
                "sentinelscale_baseline_hpa_divergence_pods": ("gauge", "Signed replica divergence (SentinelScale - Baseline HPA)."),
                "sentinelscale_traffic_risk": ("gauge", "Most recent assessed traffic security risk score."),
                "sentinelscale_predicted_legitimate_rps": ("gauge", "Most recent predicted legitimate demand RPS."),
                "sentinelscale_current_capacity_rps": ("gauge", "Most recent assessed cluster capacity RPS."),
                "sentinelscale_current_pods": ("gauge", "Most recent observed running pod replicas."),
                "sentinelscale_recommended_pods": ("gauge", "Most recent recommended pod replicas."),
                "sentinelscale_scheduler_running": ("gauge", "Continuous observation scheduler running state (1=running, 0=stopped)."),
                "sentinelscale_scheduler_last_success_timestamp_seconds": ("gauge", "Unix timestamp of last successful evaluation."),
                "sentinelscale_scheduler_last_failure_timestamp_seconds": ("gauge", "Unix timestamp of last failed evaluation."),
                "sentinelscale_scheduler_observations_skipped_total": ("counter", "Total cycles skipped due to single-flight lock."),
                "sentinelscale_history_records_total": ("counter", "Total historical observation records written to database."),
                "sentinelscale_history_write_failures_total": ("counter", "Total historical database write errors."),
                "sentinelscale_history_cleanup_total": ("counter", "Total historical observation records purged by retention TTL."),
            }

            def format_labels(labels: Tuple[Tuple[str, str], ...]) -> str:
                if not labels:
                    return ""
                formatted = ",".join(f'{k}="{v}"' for k, v in sorted(labels))
                return f"{{{formatted}}}"

            # Group entries by metric name
            metrics_emitted = set()

            # 1. Output Counters
            counter_groups: Dict[str, List] = defaultdict(list)
            for (name, labels), val in sorted(self._counters.items()):
                counter_groups[name].append((labels, val))

            for name, items in sorted(counter_groups.items()):
                m_type, help_str = metadata.get(name, ("counter", ""))
                lines.append(f"# HELP {name} {help_str}")
                lines.append(f"# TYPE {name} {m_type}")
                for labels, val in items:
                    lines.append(f"{name}{format_labels(labels)} {val}")
                metrics_emitted.add(name)

            # 2. Output Histograms
            for name, hist in sorted(self._histograms.items()):
                m_type, help_str = metadata.get(name, ("histogram", ""))
                lines.append(f"# HELP {name} {help_str}")
                lines.append(f"# TYPE {name} {m_type}")
                # Buckets
                for b, count in sorted(hist["buckets"].items()):
                    lines.append(f'{name}_bucket{{le="{b}"}} {count}')
                lines.append(f'{name}_bucket{{le="+Inf"}} {hist["count"]}')
                lines.append(f"{name}_sum {hist['sum']:.6f}")
                lines.append(f"{name}_count {hist['count']}")
                metrics_emitted.add(name)

            # 3. Output Gauges
            gauge_groups: Dict[str, List] = defaultdict(list)
            for (name, labels), val in sorted(self._gauges.items()):
                gauge_groups[name].append((labels, val))

            for name, items in sorted(gauge_groups.items()):
                m_type, help_str = metadata.get(name, ("gauge", ""))
                lines.append(f"# HELP {name} {help_str}")
                lines.append(f"# TYPE {name} {m_type}")
                for labels, val in items:
                    lines.append(f"{name}{format_labels(labels)} {val}")
                metrics_emitted.add(name)

            return "\n".join(lines) + "\n"

