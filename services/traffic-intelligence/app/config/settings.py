from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "traffic-intelligence"
    SERVICE_VERSION: str = "0.1.0"
    CONTRACT_VERSION: str = "1.0.0"
    MODEL_VERSION: str = "traffic-rules-v1"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8001

    # Pipeline Thresholds & Parameters
    BURST_RATIO_ELEVATED: float = 1.75
    BURST_RATIO_SPIKE: float = 2.5
    BURST_RATIO_EXTREME: float = 4.0

    IP_CONCENTRATION_HIGH: float = 0.40
    IP_CONCENTRATION_CRITICAL: float = 0.70

    UA_ANOMALY_HIGH: float = 0.35
    UA_ANOMALY_CRITICAL: float = 0.65

    ERROR_RATE_ELEVATED: float = 0.15
    ERROR_RATE_HIGH: float = 0.35

    # Classification Thresholds
    RISK_THRESHOLD_SUSPICIOUS: float = 0.50
    RISK_THRESHOLD_MALICIOUS: float = 0.80
    LEGITIMACY_THRESHOLD_HIGH: float = 0.65

    # Observation Window baseline
    MIN_WINDOW_SECONDS_CONFIDENCE: int = 30
    IDEAL_WINDOW_SECONDS_CONFIDENCE: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
