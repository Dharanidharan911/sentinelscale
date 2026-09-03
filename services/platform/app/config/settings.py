from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "platform"
    SERVICE_VERSION: str = "0.1.0"
    CONTRACT_VERSION: str = "1.0.0"
    MODEL_VERSION: str = "policy-rules-v0"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8003

    # Telemetry Provider Configuration: "mock" | "prometheus" | "kubernetes" | "hybrid"
    TELEMETRY_PROVIDER: str = "mock"

    # Upstream Prometheus Telemetry Configuration
    PROMETHEUS_URL: str = "http://prometheus:9090"
    PROMETHEUS_TIMEOUT_SECONDS: float = 5.0
    PROMETHEUS_QUERY_WINDOW: str = "1m"

    # Upstream Kubernetes API Telemetry Configuration
    KUBERNETES_API_URL: Optional[str] = None
    KUBERNETES_TOKEN: Optional[str] = None
    KUBECONFIG_PATH: Optional[str] = None
    KUBERNETES_TIMEOUT_SECONDS: float = 5.0

    # Upstream Intelligence URLs
    TRAFFIC_INTELLIGENCE_URL: str = "http://traffic-intelligence:8001"
    DEMAND_INTELLIGENCE_URL: str = "http://demand-intelligence:8002"

    # Safety Guardrails
    SENTINEL_DRY_RUN: bool = True
    SENTINEL_SHADOW_MODE: bool = True
    SENTINEL_AUTONOMOUS_ACTIONS_ENABLED: bool = False

    # Configuration-Based Capacity & Resource Baseline Assumptions
    DEFAULT_POD_RPS_CAPACITY: float = 350.0
    DEFAULT_MIN_PODS: int = 2
    DEFAULT_MAX_PODS: int = 20
    DEFAULT_TARGET_CPU_UTILIZATION: float = 0.70
    DEFAULT_BASELINE_RUNNING_PODS: int = 4
    DEFAULT_BASELINE_CPU_LIMIT_CORES: float = 8.0
    DEFAULT_BASELINE_CPU_REQUESTED_CORES: float = 4.0
    DEFAULT_BASELINE_MEMORY_LIMIT_BYTES: int = 8 * 1024 * 1024 * 1024       # 8 GiB
    DEFAULT_BASELINE_MEMORY_REQUESTED_BYTES: int = 4 * 1024 * 1024 * 1024   # 4 GiB

    # Continuous Observation Scheduler Configuration (Phase 4A)
    OBSERVATION_SCHEDULER_ENABLED: bool = False
    OBSERVATION_INTERVAL_SECONDS: float = Field(default=15.0, gt=0.0, description="Periodic observation interval in seconds.")
    OBSERVATION_TARGET_NAMESPACE: str = "sentinelscale"
    OBSERVATION_TARGET_WORKLOAD: str = "demo-api"
    OBSERVATION_WINDOW_SECONDS: int = Field(default=60, ge=1, description="Observation time window for Traffic Intelligence.")
    OBSERVATION_FORECAST_HORIZON_SECONDS: int = Field(default=300, ge=1, description="Forecasting horizon for Demand Intelligence.")
    OBSERVATION_EVALUATION_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0.0, description="Max execution timeout per scheduled evaluation.")

    # Decision History & Audit Store Configuration (Phase 4B)
    DECISION_HISTORY_ENABLED: bool = True
    DECISION_HISTORY_DB_PATH: str = "./data/sentinelscale_history.db"
    DECISION_HISTORY_RETENTION_DAYS: int = Field(default=7, ge=1, description="Observation history retention period in days.")

    # Operational Metrics & Observability Configuration (Phase 4C)
    METRICS_ENABLED: bool = True

    @field_validator("OBSERVATION_INTERVAL_SECONDS")
    @classmethod
    def validate_interval(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("OBSERVATION_INTERVAL_SECONDS must be strictly positive.")
        return v

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
