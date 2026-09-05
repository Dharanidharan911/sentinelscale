"""
Reproducible Traffic Dataset Generator for Module 1 (Traffic Intelligence).

Generates synthetic evaluation datasets by sampling from parameter spaces across
the four canonical SentinelScale traffic scenarios:
  Scenario A: Steady Legitimate
  Scenario B: Legitimate Flash Crowd (Organic Demand Surge)
  Scenario C: Hostile L7 (DDoS / Scraper / Credential Stuffing)
  Scenario D: Mixed (Legitimate Baseline + Background Threat)

Produces scenario-derived labels: LEGITIMATE, MALICIOUS, MIXED.
"""

import argparse
import json
from pathlib import Path
import random
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Ensure services/traffic-intelligence is on sys.path
_service_root = Path(__file__).resolve().parents[1]
if str(_service_root) not in sys.path:
    sys.path.insert(0, str(_service_root))

from app.models.traffic import StatusCodeDistribution, TrafficTelemetryInput
from app.pipeline.features import ExtractedTrafficFeatures, FeatureExtractor


class ScenarioLabel:
    LEGITIMATE = "LEGITIMATE"
    MALICIOUS = "MALICIOUS"
    MIXED = "MIXED"


@dataclass
class DatasetRecord:
    timestamp: str
    scenario_id: str
    scenario_name: str
    scenario_derived_label: str
    window_seconds: int
    raw_telemetry: Dict
    features: Dict


class TrafficDatasetGenerator:
    """Deterministic generator for synthetic scenario datasets."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)

    def generate_scenario_a_sample(self, window_seconds: int = 60) -> Tuple[TrafficTelemetryInput, str]:
        """Scenario A — Steady Legitimate Traffic."""
        baseline_rps = self.rng.uniform(40.0, 120.0)
        total_rps = round(baseline_rps * self.rng.uniform(0.85, 1.15), 2)
        total_requests = int(total_rps * window_seconds)

        err_4xx = int(total_requests * self.rng.uniform(0.005, 0.03))
        err_5xx = int(total_requests * self.rng.uniform(0.000, 0.005))
        status_3xx = int(total_requests * self.rng.uniform(0.01, 0.04))
        status_2xx = total_requests - (err_4xx + err_5xx + status_3xx)

        telemetry = TrafficTelemetryInput(
            total_requests=total_requests,
            total_rps=total_rps,
            baseline_rps=round(baseline_rps, 2),
            status_codes=StatusCodeDistribution(
                status_2xx=status_2xx,
                status_3xx=status_3xx,
                status_4xx=err_4xx,
                status_5xx=err_5xx,
            ),
            top_ip_ratio=round(self.rng.uniform(0.01, 0.08), 3),
            unique_ip_count=int(total_requests * self.rng.uniform(0.20, 0.40)),
            non_standard_ua_ratio=round(self.rng.uniform(0.00, 0.04), 3),
            single_endpoint_ratio=round(self.rng.uniform(0.15, 0.40), 3),
        )
        return telemetry, ScenarioLabel.LEGITIMATE

    def generate_scenario_b_sample(self, window_seconds: int = 60) -> Tuple[TrafficTelemetryInput, str]:
        """Scenario B — Legitimate Flash Crowd (Organic Demand Surge)."""
        baseline_rps = self.rng.uniform(50.0, 100.0)
        burst_factor = self.rng.uniform(2.5, 6.0)
        total_rps = round(baseline_rps * burst_factor, 2)
        total_requests = int(total_rps * window_seconds)

        err_4xx = int(total_requests * self.rng.uniform(0.01, 0.04))
        err_5xx = int(total_requests * self.rng.uniform(0.001, 0.01))
        status_3xx = int(total_requests * self.rng.uniform(0.01, 0.03))
        status_2xx = total_requests - (err_4xx + err_5xx + status_3xx)

        telemetry = TrafficTelemetryInput(
            total_requests=total_requests,
            total_rps=total_rps,
            baseline_rps=round(baseline_rps, 2),
            status_codes=StatusCodeDistribution(
                status_2xx=status_2xx,
                status_3xx=status_3xx,
                status_4xx=err_4xx,
                status_5xx=err_5xx,
            ),
            top_ip_ratio=round(self.rng.uniform(0.02, 0.09), 3),  # Still widely distributed
            unique_ip_count=int(total_requests * self.rng.uniform(0.25, 0.50)),
            non_standard_ua_ratio=round(self.rng.uniform(0.00, 0.05), 3),
            single_endpoint_ratio=round(self.rng.uniform(0.25, 0.55), 3),
        )
        return telemetry, ScenarioLabel.LEGITIMATE

    def generate_scenario_c_sample(self, window_seconds: int = 60) -> Tuple[TrafficTelemetryInput, str]:
        """Scenario C — Hostile L7 Flood / Attack Swarm."""
        baseline_rps = self.rng.uniform(40.0, 100.0)
        burst_factor = self.rng.uniform(4.0, 15.0)
        total_rps = round(baseline_rps * burst_factor, 2)
        total_requests = int(total_rps * window_seconds)

        err_4xx = int(total_requests * self.rng.uniform(0.40, 0.85))
        err_5xx = int(total_requests * self.rng.uniform(0.05, 0.20))
        status_3xx = int(total_requests * self.rng.uniform(0.00, 0.02))
        status_2xx = max(0, total_requests - (err_4xx + err_5xx + status_3xx))

        telemetry = TrafficTelemetryInput(
            total_requests=total_requests,
            total_rps=total_rps,
            baseline_rps=round(baseline_rps, 2),
            status_codes=StatusCodeDistribution(
                status_2xx=status_2xx,
                status_3xx=status_3xx,
                status_4xx=err_4xx,
                status_5xx=err_5xx,
            ),
            top_ip_ratio=round(self.rng.uniform(0.60, 0.95), 3),  # High IP concentration
            unique_ip_count=self.rng.randint(5, 50),
            non_standard_ua_ratio=round(self.rng.uniform(0.60, 0.98), 3),  # Bots/scrapers
            single_endpoint_ratio=round(self.rng.uniform(0.75, 0.99), 3),  # Single target flood
        )
        return telemetry, ScenarioLabel.MALICIOUS

    def generate_scenario_d_sample(self, window_seconds: int = 60) -> Tuple[TrafficTelemetryInput, str]:
        """Scenario D — Mixed Traffic (Legitimate Baseline + Background Attack/Scraper)."""
        baseline_rps = self.rng.uniform(50.0, 120.0)
        burst_factor = self.rng.uniform(1.8, 3.5)
        total_rps = round(baseline_rps * burst_factor, 2)
        total_requests = int(total_rps * window_seconds)

        err_4xx = int(total_requests * self.rng.uniform(0.18, 0.38))
        err_5xx = int(total_requests * self.rng.uniform(0.02, 0.08))
        status_3xx = int(total_requests * self.rng.uniform(0.02, 0.05))
        status_2xx = total_requests - (err_4xx + err_5xx + status_3xx)

        telemetry = TrafficTelemetryInput(
            total_requests=total_requests,
            total_rps=total_rps,
            baseline_rps=round(baseline_rps, 2),
            status_codes=StatusCodeDistribution(
                status_2xx=status_2xx,
                status_3xx=status_3xx,
                status_4xx=err_4xx,
                status_5xx=err_5xx,
            ),
            top_ip_ratio=round(self.rng.uniform(0.35, 0.55), 3),  # Moderate concentration
            unique_ip_count=int(total_requests * self.rng.uniform(0.10, 0.25)),
            non_standard_ua_ratio=round(self.rng.uniform(0.30, 0.55), 3),  # Mixed UA
            single_endpoint_ratio=round(self.rng.uniform(0.50, 0.75), 3),
        )
        return telemetry, ScenarioLabel.MIXED

    def generate_dataset(
        self,
        samples_per_scenario: int = 50,
        window_seconds: int = 60
    ) -> List[DatasetRecord]:
        """Generates a balanced dataset across the four scenarios."""
        records: List[DatasetRecord] = []
        generators = [
            ("A", "Steady Legitimate", self.generate_scenario_a_sample),
            ("B", "Legitimate Flash Crowd", self.generate_scenario_b_sample),
            ("C", "Hostile L7", self.generate_scenario_c_sample),
            ("D", "Mixed Traffic", self.generate_scenario_d_sample),
        ]

        timestamp = datetime.now(timezone.utc).isoformat()

        for scenario_id, scenario_name, gen_func in generators:
            for _ in range(samples_per_scenario):
                telemetry, label = gen_func(window_seconds=window_seconds)
                features = FeatureExtractor.extract(telemetry, window_seconds=window_seconds)

                records.append(
                    DatasetRecord(
                        timestamp=timestamp,
                        scenario_id=scenario_id,
                        scenario_name=scenario_name,
                        scenario_derived_label=label,
                        window_seconds=window_seconds,
                        raw_telemetry=telemetry.model_dump(),
                        features=asdict(features),
                    )
                )

        # Shuffle deterministically
        self.rng.shuffle(records)
        return records


def main():
    parser = argparse.ArgumentParser(description="Generate reproducible synthetic traffic dataset.")
    parser.add_argument("--samples-per-scenario", type=int, default=50, help="Samples per scenario (total = 4x)")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path (optional)")
    args = parser.parse_args()

    generator = TrafficDatasetGenerator(seed=args.seed)
    records = generator.generate_dataset(samples_per_scenario=args.samples_per_scenario)

    print(f"Generated {len(records)} records across 4 canonical scenarios (seed={args.seed}).")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in records], f, indent=2)
        print(f"Saved dataset to {out_path}")
    else:
        # Print summary
        counts = {}
        for r in records:
            counts[r.scenario_derived_label] = counts.get(r.scenario_derived_label, 0) + 1
        print("Label counts:", counts)


if __name__ == "__main__":
    main()
