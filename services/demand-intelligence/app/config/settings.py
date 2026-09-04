from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    SERVICE_NAME: str = "demand-intelligence"
    SERVICE_VERSION: str = "0.1.0"
    CONTRACT_VERSION: str = "1.0.0"
    MODEL_VERSION: str = "demand-v1"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8002

    # Forecasting Engine Configuration
    FORECAST_MIN_OBSERVATIONS: int = 2
    FORECAST_MIN_OBSERVATIONS_FOR_TREND: int = 5
    FORECAST_RECENCY_WEIGHT_DECAY: float = 0.85
    FORECAST_RECENCY_REFERENCE_INTERVAL_SECONDS: float = 30.0
    FORECAST_MIN_TIME_SPAN_FOR_TREND: float = 120.0
    FORECAST_MAX_TREND_SLOPE: float = 10.0
    FORECAST_SAMPLE_CONFIDENCE_SCALE: float = 30.0
    FORECAST_VARIANCE_CONFIDENCE_SCALE: float = 0.15
    FORECAST_INTERVAL_HALF_WIDTH_SIGMA: float = 1.5

    # Prometheus is intentionally opt-in.  An empty URL preserves the
    # deterministic mock provider for local development and test runs.
    PROMETHEUS_URL: str = ""
    PROMETHEUS_QUERY: str = (
        'sum(rate(http_requests_total{service="{target_service}"}[1m]))'
    )
    PROMETHEUS_STEP_SECONDS: int = Field(default=30, ge=1)
    PROMETHEUS_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0.0)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
