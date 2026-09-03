from dataclasses import dataclass
from typing import Optional
from app.models.traffic import TrafficTelemetryInput


@dataclass(frozen=True)
class ExtractedTrafficFeatures:
    """Normalized feature representations extracted from raw traffic telemetry."""
    total_rps: float
    burst_ratio: float
    error_rate: float
    ip_concentration: float
    ua_anomaly_ratio: float
    single_endpoint_ratio: float
    has_telemetry: bool
    data_completeness: float  # 0.0 to 1.0


class FeatureExtractor:
    """Extracts and normalizes features from raw traffic telemetry."""

    @staticmethod
    def extract(
        telemetry: Optional[TrafficTelemetryInput],
        window_seconds: int = 60
    ) -> ExtractedTrafficFeatures:
        if telemetry is None:
            # When telemetry is not provided, represent missing evidence cleanly
            return ExtractedTrafficFeatures(
                total_rps=0.0,
                burst_ratio=1.0,
                error_rate=0.0,
                ip_concentration=0.0,
                ua_anomaly_ratio=0.0,
                single_endpoint_ratio=0.0,
                has_telemetry=False,
                data_completeness=0.0,
            )

        total_rps = float(telemetry.total_rps)

        # 1. Burst Ratio: observed RPS vs baseline RPS
        if telemetry.baseline_rps and telemetry.baseline_rps > 0:
            burst_ratio = round(total_rps / telemetry.baseline_rps, 3)
        else:
            burst_ratio = 1.0

        # 2. Error Rate: (4xx + 5xx) / total requests
        if telemetry.status_codes and telemetry.status_codes.total_requests > 0:
            error_rate = round(telemetry.status_codes.error_rate, 4)
        else:
            error_rate = 0.0

        # 3. Client IP concentration
        ip_concentration = float(telemetry.top_ip_ratio or 0.0)

        # 4. User-Agent anomaly ratio
        ua_anomaly_ratio = float(telemetry.non_standard_ua_ratio or 0.0)

        # 5. Single endpoint concentration ratio
        single_endpoint_ratio = float(telemetry.single_endpoint_ratio or 0.0)

        # 6. Data Completeness metric based on provided fields
        fields_evaluated = [
            telemetry.baseline_rps is not None,
            telemetry.status_codes is not None,
            telemetry.top_ip_ratio is not None,
            telemetry.non_standard_ua_ratio is not None,
            telemetry.single_endpoint_ratio is not None,
        ]
        data_completeness = round(sum(fields_evaluated) / len(fields_evaluated), 2)

        return ExtractedTrafficFeatures(
            total_rps=total_rps,
            burst_ratio=burst_ratio,
            error_rate=error_rate,
            ip_concentration=ip_concentration,
            ua_anomaly_ratio=ua_anomaly_ratio,
            single_endpoint_ratio=single_endpoint_ratio,
            has_telemetry=True,
            data_completeness=data_completeness,
        )

