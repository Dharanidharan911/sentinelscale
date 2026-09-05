"""
SentinelScale — Demand Intelligence — Error Types
Explicit error hierarchy. Never silently convert failures into misleading values.
"""


class DemandIntelligenceError(Exception):
    """Base error for Demand Intelligence module."""
    pass


class InsufficientDataError(DemandIntelligenceError):
    """
    Raised when there are not enough demand observations to produce a
    meaningful forecast. Distinct from zero demand — this means no data,
    not zero traffic.
    """
    def __init__(self, required: int, available: int):
        self.required = required
        self.available = available
        super().__init__(
            f"Insufficient demand observations: required {required}, available {available}. "
            f"Cannot produce a forecast — this is a data availability error, not zero demand."
        )


class InvalidObservationError(DemandIntelligenceError):
    """
    Raised when an observation contains invalid data that cannot be safely
    used in forecasting (e.g. negative RPS, non-numeric values).
    """
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Invalid demand observation: {reason}")


class ProviderUnavailableError(DemandIntelligenceError):
    """
    Raised when the demand data provider cannot be reached or returns
    no usable data. Distinct from InsufficientDataError.
    """
    def __init__(self, provider_name: str, reason: str):
        self.provider_name = provider_name
        self.reason = reason
        super().__init__(
            f"Demand provider '{provider_name}' unavailable: {reason}"
        )


class ForecastCalculationError(DemandIntelligenceError):
    """
    Raised when the forecasting engine encounters an unexpected calculation
    error after receiving valid data.
    """
    pass
