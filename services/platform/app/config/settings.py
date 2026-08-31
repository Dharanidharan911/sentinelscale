from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "platform"
    SERVICE_VERSION: str = "0.1.0"
    CONTRACT_VERSION: str = "1.0.0"
    MODEL_VERSION: str = "policy-rules-v0"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8003

    # Telemetry Provider Configuration: "mock" | "prometheus" | "kubernetes"
    TELEMETRY_PROVIDER: str = "mock"

    # Upstream Intelligence URLs
    TRAFFIC_INTELLIGENCE_URL: str = "http://traffic-intelligence:8001"
    DEMAND_INTELLIGENCE_URL: str = "http://demand-intelligence:8002"
    PROMETHEUS_URL: str = "http://prometheus:9090"

    # Safety Guardrails
    SENTINEL_DRY_RUN: bool = True
    SENTINEL_SHADOW_MODE: bool = True
    SENTINEL_AUTONOMOUS_ACTIONS_ENABLED: bool = False

    # Capacity & Scaling Defaults
    DEFAULT_POD_RPS_CAPACITY: float = 350.0
    DEFAULT_MIN_PODS: int = 2
    DEFAULT_MAX_PODS: int = 20
    DEFAULT_TARGET_CPU_UTILIZATION: float = 0.70

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
