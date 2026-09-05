"""Regression tests for explicit demand-observation quality semantics."""
import math
import time

import pytest
from pydantic import ValidationError

from app.config.settings import settings
from app.engine.preprocessor import preprocess_observations
from app.errors import InvalidObservationError
from app.models.demand import DemandObservation


class TestObservationModelDataQuality:
    @pytest.mark.parametrize("timestamp", [math.nan, math.inf, -math.inf])
    def test_non_finite_timestamp_is_rejected(self, timestamp):
        with pytest.raises(ValidationError, match="timestamp must be finite"):
            DemandObservation(timestamp=timestamp, rps=10.0)

    @pytest.mark.parametrize("rps", [math.nan, math.inf, -math.inf])
    def test_non_finite_rps_is_rejected(self, rps):
        with pytest.raises(ValidationError):
            DemandObservation(timestamp=1_700_000_000.0, rps=rps)

    def test_timestamp_beyond_clock_skew_is_rejected(self):
        timestamp = time.time() + settings.OBSERVATION_MAX_FUTURE_SKEW_SECONDS + 1.0
        with pytest.raises(ValidationError, match="too far in the future"):
            DemandObservation(timestamp=timestamp, rps=10.0)


class TestPreprocessorDataQualityDefenceInDepth:
    @pytest.mark.parametrize("timestamp,rps", [
        (math.nan, 10.0),
        (math.inf, 10.0),
        (1_700_000_000.0, math.nan),
        (1_700_000_000.0, math.inf),
        (time.time() + settings.OBSERVATION_MAX_FUTURE_SKEW_SECONDS + 60.0, 10.0),
    ])
    def test_bypassed_model_validation_still_fails_explicitly(self, timestamp, rps):
        invalid = DemandObservation.model_construct(timestamp=timestamp, rps=rps)
        with pytest.raises(InvalidObservationError):
            preprocess_observations([invalid])
