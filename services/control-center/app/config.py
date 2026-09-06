from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "control-center"
    SERVICE_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    PORT: int = 8080
    PLATFORM_URL: str = "http://platform:8003"
    GRAFANA_URL: str = "http://localhost:3000"
    TEMPO_URL: str = "http://localhost:3200"
    LOKI_URL: str = "http://localhost:3100"
    PROMETHEUS_URL: str = "http://localhost:9090"

    DEFAULT_NAMESPACE: str = "default"
    DEFAULT_WORKLOAD: str = "demo-api"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

