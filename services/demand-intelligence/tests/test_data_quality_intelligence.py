"""
SentinelScale — Demand Intelligence — Test: Data Quality Intelligence (M2-12)
Validates completeness, regularity, staleness, noise metrics, and categorical ratings.
"""
import pytest
from app.models.demand import DemandObservation
from app.engine.data_quality import DataQualityAssessor, DataQualityReport


def _obs(ts, rps):
    return DemandObservation(timestamp=ts, rps=rps)


class TestDataQualityIntelligence:
    def test_empty_observations(self):
        report = DataQualityAssessor.assess([])
        assert report.sample_count == 0
        assert report.quality_score == 0.0
        assert report.quality_rating == "POOR"

    def test_single_observation(self):
        report = DataQualityAssessor.assess([_obs(100.0, 50.0)])
        assert report.sample_count == 1
        assert report.quality_rating == "POOR"

    def test_excellent_regular_dataset(self):
        """Uniform 30s cadence, 20 observations, low noise -> EXCELLENT."""
        data = [_obs(1000.0 + i * 30.0, 500.0 + (i % 3) * 2.0) for i in range(20)]
        report = DataQualityAssessor.assess(data, reference_time=1000.0 + 19 * 30.0)
        assert report.sample_count == 20
        assert report.cadence_seconds == 30.0
        assert report.completeness_ratio >= 0.95
        assert report.cadence_regularity >= 0.95
        assert report.staleness_seconds == 0.0
        assert report.quality_rating == "EXCELLENT"
        assert report.quality_score >= 0.80

    def test_irregular_cadence_degrades_score(self):
        """Jittery/irregular timestamps reduce regularity and quality score."""
        regular = [_obs(1000.0 + i * 30.0, 500.0) for i in range(10)]
        irregular = [
            _obs(1000.0, 500.0),
            _obs(1005.0, 500.0),
            _obs(1200.0, 500.0),
            _obs(1210.0, 500.0),
            _obs(1800.0, 500.0),
            _obs(1805.0, 500.0),
            _obs(2500.0, 500.0),
            _obs(2510.0, 500.0),
            _obs(3500.0, 500.0),
            _obs(3510.0, 500.0),
        ]
        rep_reg = DataQualityAssessor.assess(regular, reference_time=regular[-1].timestamp)
        rep_irreg = DataQualityAssessor.assess(irregular, reference_time=irregular[-1].timestamp)

        assert rep_irreg.cadence_regularity < rep_reg.cadence_regularity
        assert rep_irreg.quality_score < rep_reg.quality_score

    def test_staleness_degrades_quality_score(self):
        """A stale series (last observation was 1 hour ago) has reduced quality."""
        data = [_obs(1000.0 + i * 30.0, 500.0) for i in range(15)]
        fresh_report = DataQualityAssessor.assess(data, reference_time=1000.0 + 14 * 30.0)
        stale_report = DataQualityAssessor.assess(data, reference_time=1000.0 + 14 * 30.0 + 3600.0)

        assert stale_report.staleness_seconds == 3600.0
        assert stale_report.quality_score < fresh_report.quality_score

    def test_high_noise_increases_noise_ratio(self):
        """Volatile observations reflect higher noise ratio."""
        stable = [_obs(1000.0 + i * 30.0, 500.0) for i in range(15)]
        noisy = [_obs(1000.0 + i * 30.0, 500.0 + (500.0 if i % 2 == 0 else -300.0)) for i in range(15)]

        rep_stable = DataQualityAssessor.assess(stable, reference_time=stable[-1].timestamp)
        rep_noisy = DataQualityAssessor.assess(noisy, reference_time=noisy[-1].timestamp)

        assert rep_noisy.noise_to_signal_ratio > rep_stable.noise_to_signal_ratio
        assert rep_noisy.quality_score < rep_stable.quality_score
