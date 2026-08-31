from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "demand-intelligence"
    SERVICE_VERSION: str = "0.1.0"
    CONTRACT_VERSION: str = "1.0.0"
    MODEL_VERSION: str = "demand-v0"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8002

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
