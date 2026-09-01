import re
from typing import Union
from app.services.telemetry.base import TelemetryProviderError

# Regular expression for Kubernetes CPU quantities
# Examples: "100m", "500m", "1", "0.5", "2.4"
_CPU_REGEX = re.compile(r"^([0-9]+(?:\.[0-9]+)?)(m)?$")

# Binary SI units (powers of 1024): Ki, Mi, Gi, Ti, Pi, Ei
_BINARY_SI_MULTIPLIERS = {
    "Ki": 1024,
    "Mi": 1024 ** 2,
    "Gi": 1024 ** 3,
    "Ti": 1024 ** 4,
    "Pi": 1024 ** 5,
    "Ei": 1024 ** 6,
}

# Decimal SI units (powers of 1000): k (or K), M, G, T, P, E
_DECIMAL_SI_MULTIPLIERS = {
    "k": 1000,
    "K": 1000,
    "M": 1000 ** 2,
    "G": 1000 ** 3,
    "T": 1000 ** 4,
    "P": 1000 ** 5,
    "E": 1000 ** 6,
}


def parse_cpu_quantity(value: Union[str, int, float, None]) -> float:
    """
    Parse a Kubernetes CPU quantity into canonical float cores.

    Supported Kubernetes syntax:
      - Millicores: "100m" -> 0.1, "500m" -> 0.5, "1500m" -> 1.5
      - Plain numeric / decimal cores: "1" -> 1.0, "0.5" -> 0.5, 2 -> 2.0

    Raises TelemetryProviderError on malformed, negative, or unknown syntax.
    """
    if value is None:
        return 0.0

    if isinstance(value, (int, float)):
        if value < 0:
            raise TelemetryProviderError(
                provider_name="kubernetes",
                message=f"Negative CPU quantity is invalid: {value}"
            )
        return float(value)

    val_str = str(value).strip()
    if not val_str:
        return 0.0

    match = _CPU_REGEX.match(val_str)
    if not match:
        raise TelemetryProviderError(
            provider_name="kubernetes",
            message=f"Malformed Kubernetes CPU quantity: '{val_str}'"
        )

    num_part, unit_part = match.groups()
    num = float(num_part)

    if unit_part == "m":
        cores = num / 1000.0
    else:
        cores = num

    if cores < 0.0:
        raise TelemetryProviderError(
            provider_name="kubernetes",
            message=f"Negative CPU quantity is invalid: '{val_str}'"
        )

    return round(cores, 6)


def parse_memory_quantity(value: Union[str, int, float, None]) -> int:
    """
    Parse a Kubernetes Memory quantity into canonical integer bytes.

    Supported Kubernetes syntax:
      - Binary SI units (powers of 1024): "128Ki", "256Mi", "4Gi", "1Ti"
      - Decimal SI units (powers of 1000): "100k", "500M", "2G"
      - Plain integer bytes: "1048576", 52428800

    Raises TelemetryProviderError on malformed, negative, or unknown suffix.
    """
    if value is None:
        return 0

    if isinstance(value, int):
        if value < 0:
            raise TelemetryProviderError(
                provider_name="kubernetes",
                message=f"Negative memory quantity is invalid: {value}"
            )
        return value

    if isinstance(value, float):
        if value < 0:
            raise TelemetryProviderError(
                provider_name="kubernetes",
                message=f"Negative memory quantity is invalid: {value}"
            )
        return int(value)

    val_str = str(value).strip()
    if not val_str:
        return 0

    # 1. Check Binary SI suffix (Ki, Mi, Gi, Ti, Pi, Ei)
    for suffix, multiplier in _BINARY_SI_MULTIPLIERS.items():
        if val_str.endswith(suffix):
            num_part = val_str[:-len(suffix)].strip()
            try:
                num = float(num_part)
                if num < 0:
                    raise ValueError("Negative value")
                return int(num * multiplier)
            except ValueError as err:
                raise TelemetryProviderError(
                    provider_name="kubernetes",
                    message=f"Malformed numeric part in memory quantity: '{val_str}'",
                    original_error=err
                ) from err

    # 2. Check Decimal SI suffix (k, K, M, G, T, P, E)
    for suffix, multiplier in _DECIMAL_SI_MULTIPLIERS.items():
        if val_str.endswith(suffix):
            num_part = val_str[:-len(suffix)].strip()
            try:
                num = float(num_part)
                if num < 0:
                    raise ValueError("Negative value")
                return int(num * multiplier)
            except ValueError as err:
                raise TelemetryProviderError(
                    provider_name="kubernetes",
                    message=f"Malformed numeric part in memory quantity: '{val_str}'",
                    original_error=err
                ) from err

    # 3. Check plain integer bytes
    if re.match(r"^[0-9]+$", val_str):
        return int(val_str)

    # 4. Check decimal without suffix
    if re.match(r"^[0-9]+\.[0-9]+$", val_str):
        return int(float(val_str))

    raise TelemetryProviderError(
        provider_name="kubernetes",
        message=f"Malformed or unsupported Kubernetes memory quantity: '{val_str}'"
    )

