"""
SentinelScale — Historical Demand Observation Accumulator
Stage F2 Platform-side service that transforms successive M1 TrafficAssessments
into a bounded, validated, deduplicated historical sequence of DemandObservations.
"""
import math
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.config.settings import settings
from app.logging import logger
from app.models.demand_contract import DemandObservation
from app.models.traffic_contract import TrafficAssessment, TrafficClassification


class InvalidAssessmentError(ValueError):
    """Raised when a TrafficAssessment contains invalid, malformed, or infinite values."""
    pass


class DemandObservationAccumulator:
    """
    Thread-safe SQLite-backed accumulator for legitimate demand observations.
    Reuses Platform's centralized database infrastructure.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path if db_path is not None else settings.DECISION_HISTORY_DB_PATH
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._initialize_database()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.db_path != ":memory:":
                dirname = os.path.dirname(os.path.abspath(self.db_path))
                if dirname:
                    os.makedirs(dirname, exist_ok=True)

            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            if self.db_path != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL;")
            self._conn = conn
        return self._conn

    def _initialize_database(self) -> None:
        """Idempotently create demand_observations table and indexes."""
        with self._lock:
            conn = self._get_connection()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS demand_observations (
                    event_id TEXT PRIMARY KEY,
                    target_service TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    timestamp_epoch REAL NOT NULL,
                    timestamp_iso TEXT NOT NULL,
                    legitimate_rps REAL NOT NULL,
                    risk_score REAL NOT NULL,
                    legitimacy_score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    classification TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_demand_obs_target_time ON demand_observations(target_service, timestamp_epoch ASC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_demand_obs_epoch ON demand_observations(timestamp_epoch);")
            conn.commit()

    @staticmethod
    def parse_iso_timestamp(iso_str: str) -> float:
        """
        Convert ISO-8601 string from TrafficAssessment into Unix epoch float.
        Raises InvalidAssessmentError if malformed or non-finite.
        """
        if not iso_str or not isinstance(iso_str, str):
            raise InvalidAssessmentError(f"Invalid timestamp format: {iso_str}")
        try:
            # Normalize trailing Z to +00:00 for standard python fromisoformat
            normalized = iso_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            epoch_seconds = dt.timestamp()
            if not math.isfinite(epoch_seconds) or epoch_seconds <= 0:
                raise InvalidAssessmentError(f"Timestamp epoch must be positive and finite: {epoch_seconds}")
            return epoch_seconds
        except (ValueError, TypeError) as exc:
            raise InvalidAssessmentError(f"Failed to parse ISO-8601 timestamp '{iso_str}': {exc}") from exc

    def record_traffic_assessment(
        self,
        assessment: TrafficAssessment,
        target_service: str = "demo-api",
    ) -> Optional[DemandObservation]:
        """
        Ingest a single TrafficAssessment from Module 1.
        
        Performs:
        1. Strict validation (finite positive timestamps, finite non-negative RPS).
        2. Security / Suspicious-Traffic filtering.
        3. Deduplication by event_id.
        4. Persistence to the observation history store.
        
        Returns:
            DemandObservation if accepted and stored, or None if filtered out by security policy.
        """
        # 1. Validate Timestamp
        timestamp_epoch = self.parse_iso_timestamp(assessment.timestamp)

        # 2. Validate Legitimate RPS
        legit_rps = assessment.legitimate_rps_estimate
        if legit_rps is None or not math.isfinite(legit_rps):
            raise InvalidAssessmentError(f"legitimate_rps_estimate must be finite, got: {legit_rps}")
        if legit_rps < 0.0:
            raise InvalidAssessmentError(f"legitimate_rps_estimate cannot be negative, got: {legit_rps}")

        # 3. Validate Scores
        for score_name, score_val in [
            ("risk_score", assessment.risk_score),
            ("legitimacy_score", assessment.legitimacy_score),
            ("confidence", assessment.confidence),
        ]:
            if not math.isfinite(score_val) or score_val < 0.0 or score_val > 1.0:
                raise InvalidAssessmentError(f"{score_name} must be finite between 0.0 and 1.0, got: {score_val}")

        # 4. Security & Suspicious-Traffic Policy Filtering
        # Invariant: Attack traffic must NEVER become accumulated legitimate demand.
        classification_str = (
            assessment.classification.value
            if hasattr(assessment.classification, "value")
            else str(assessment.classification)
        )

        if classification_str.lower() == TrafficClassification.MALICIOUS.value or assessment.risk_score > settings.DEMAND_OBSERVATION_MAX_RISK:
            logger.info(
                "Filtered hostile TrafficAssessment from demand observation accumulation",
                extra={
                    "event_id": assessment.event_id,
                    "target_service": target_service,
                    "risk_score": assessment.risk_score,
                    "classification": classification_str,
                },
            )
            return None

        if assessment.legitimacy_score < settings.DEMAND_OBSERVATION_MIN_LEGITIMACY:
            logger.info(
                "Filtered low-legitimacy TrafficAssessment from demand accumulation",
                extra={
                    "event_id": assessment.event_id,
                    "target_service": target_service,
                    "legitimacy_score": assessment.legitimacy_score,
                },
            )
            return None

        if assessment.confidence < settings.DEMAND_OBSERVATION_MIN_CONFIDENCE:
            logger.info(
                "Filtered low-confidence TrafficAssessment from demand accumulation",
                extra={
                    "event_id": assessment.event_id,
                    "target_service": target_service,
                    "confidence": assessment.confidence,
                },
            )
            return None

        # 5. Persist with Deduplication
        recorded_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT OR REPLACE INTO demand_observations (
                    event_id, target_service, trace_id, timestamp_epoch, timestamp_iso,
                    legitimate_rps, risk_score, legitimacy_score, confidence,
                    classification, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment.event_id,
                    target_service,
                    assessment.trace_id,
                    timestamp_epoch,
                    assessment.timestamp,
                    legit_rps,
                    assessment.risk_score,
                    assessment.legitimacy_score,
                    assessment.confidence,
                    classification_str,
                    recorded_at,
                ),
            )
            conn.commit()

        return DemandObservation(timestamp=timestamp_epoch, rps=legit_rps)

    def get_historical_demand_observations(
        self,
        target_service: str = "demo-api",
        historical_window_seconds: Optional[int] = None,
        now_epoch: Optional[float] = None,
    ) -> List[DemandObservation]:
        """
        Retrieve chronological legitimate demand observations for a target service.
        
        Args:
            target_service: The workload identifier.
            historical_window_seconds: Lookback horizon in seconds (default from settings).
            now_epoch: Reference time for window calculation (default: time.time()).
            
        Returns:
            List of DemandObservation instances ordered strictly chronologically (oldest first).
        """
        window = historical_window_seconds or settings.DEMAND_OBSERVATION_HISTORY_WINDOW_SECONDS
        reference_time = now_epoch if now_epoch is not None else time.time()
        start_epoch = reference_time - window

        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                SELECT timestamp_epoch, legitimate_rps
                FROM demand_observations
                WHERE target_service = ?
                  AND timestamp_epoch >= ?
                  AND timestamp_epoch <= ?
                ORDER BY timestamp_epoch ASC
                """,
                (target_service, start_epoch, reference_time),
            )
            rows = cursor.fetchall()

        return [
            DemandObservation(timestamp=float(row["timestamp_epoch"]), rps=float(row["legitimate_rps"]))
            for row in rows
        ]

    def get_observation_count(self, target_service: str = "demo-api") -> int:
        """Return the count of stored demand observations for a service."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT COUNT(*) FROM demand_observations WHERE target_service = ?",
                (target_service,),
            )
            return cursor.fetchone()[0]

    def cleanup_old_observations(self, retention_seconds: Optional[int] = None) -> int:
        """Purge observations older than retention window. Returns count deleted."""
        retention = retention_seconds or settings.DEMAND_OBSERVATION_RETENTION_SECONDS
        cutoff = time.time() - retention

        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "DELETE FROM demand_observations WHERE timestamp_epoch < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def clear(self, target_service: Optional[str] = None) -> None:
        """Clear observations (primarily for test resets)."""
        with self._lock:
            conn = self._get_connection()
            if target_service:
                conn.execute("DELETE FROM demand_observations WHERE target_service = ?", (target_service,))
            else:
                conn.execute("DELETE FROM demand_observations")
            conn.commit()

