from typing import Optional
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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
