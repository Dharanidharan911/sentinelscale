import json
import logging
from pathlib import Path
from typing import List, Optional

from app.config.settings import settings
from app.models.experiment import (
    ExperimentResult,
    ExperimentRunSummary,
)

logger = logging.getLogger("sentinelscale.experiments")


class ExperimentResultsReader:
    """
    Read-only service for discovering and parsing canonical M3-8 experiment result files.
    Preserves strict read-only guarantees and does not mutate filesystem state.
    """

    def __init__(self, results_dir: Optional[str] = None):
        self._custom_dir = results_dir

    def _resolve_results_dir(self) -> Path:
        """
        Locates the directory containing experiment result JSON files.
        Checks custom directory, settings directory, container path, and repo root fallback.
        """
        if self._custom_dir:
            return Path(self._custom_dir).resolve()

        candidates = [
            Path(settings.EXPERIMENTS_RESULTS_DIR),
            Path("/app/experiments/results"),
            Path(__file__).resolve().parents[4] / "experiments" / "results",
        ]

        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate.resolve()

        return candidates[0].resolve()

    def list_experiments(self, scenario_id: Optional[str] = None) -> List[ExperimentRunSummary]:
        """
        Discovers and validates all experiment result JSON files.
        Returns lightweight summaries sorted by start_time descending.
        """
        results_dir = self._resolve_results_dir()
        if not results_dir.exists() or not results_dir.is_dir():
            logger.warning(f"Experiment results directory not found: {results_dir}")
            return []

        summaries: List[ExperimentRunSummary] = []

        for file_path in sorted(results_dir.glob("*.json")):
            try:
                content = file_path.read_text(encoding="utf-8")
                raw_data = json.loads(content)
                result = ExperimentResult.model_validate(raw_data)

                if scenario_id and result.scenario_id != scenario_id:
                    continue

                summary = ExperimentRunSummary(
                    run_id=result.run_id,
                    scenario_id=result.scenario_id,
                    scenario_name=result.scenario_name,
                    start_time=result.start_time,
                    end_time=result.end_time,
                    duration_seconds=result.duration_seconds,
                    workload_summary=result.workload_summary,
                    hpa_summary=result.hpa_summary,
                    sentinelscale_summary=result.sentinelscale_summary,
                    comparison_summary=result.comparison_summary,
                    performance_guardrails=result.performance_guardrails,
                    safety=result.safety,
                    has_timeseries=len(result.timeseries) > 0,
                )
                summaries.append(summary)
            except Exception as exc:
                logger.warning(
                    f"Failed to parse experiment result file {file_path.name}: {exc}"
                )
                continue

        # Sort newest first by start_time
        summaries.sort(key=lambda s: s.start_time, reverse=True)
        return summaries

    def get_experiment(self, run_id: str) -> Optional[ExperimentResult]:
        """
        Finds and returns the full ExperimentResult with complete timeseries payload.
        Returns None if not found or unparseable.
        """
        results_dir = self._resolve_results_dir()
        if not results_dir.exists() or not results_dir.is_dir():
            logger.warning(f"Experiment results directory not found: {results_dir}")
            return None

        for file_path in results_dir.glob("*.json"):
            try:
                content = file_path.read_text(encoding="utf-8")
                raw_data = json.loads(content)
                if raw_data.get("run_id") == run_id:
                    return ExperimentResult.model_validate(raw_data)
            except Exception as exc:
                logger.warning(
                    f"Failed to inspect experiment result file {file_path.name}: {exc}"
                )
                continue

        return None


# Global singleton instance
_reader_instance: Optional[ExperimentResultsReader] = None


def get_experiment_reader() -> ExperimentResultsReader:
    global _reader_instance
    if _reader_instance is None:
        _reader_instance = ExperimentResultsReader()
    return _reader_instance
