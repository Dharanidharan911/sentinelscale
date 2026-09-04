import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from app.config.settings import settings
from app.logging import logger
from app.models.decision import ScalingAction
from app.models.history import HistoryStats, StoredObservation
from app.services.history.base import DecisionHistoryStore


class SQLiteDecisionHistoryStore(DecisionHistoryStore):
    """
    Production SQLite implementation of DecisionHistoryStore.
    Stores lightweight queryable columns alongside full JSON audit payloads.
    Guarantees thread-safety, transaction isolation, and indexed fast lookups.
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
        """Idempotently create database directories and tables."""
        with self._lock:
            conn = self._get_connection()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS decision_history (
                    id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    completed_at TEXT,
                    duration_ms REAL NOT NULL DEFAULT 0.0,
                    success INTEGER NOT NULL,
                    action TEXT,
                    reason TEXT,
                    confidence REAL,
                    recommended_pods INTEGER,
                    current_pods INTEGER,
                    baseline_hpa_recommended_pods INTEGER,
                    pod_delta_vs_baseline INTEGER,
                    traffic_risk REAL,
                    predicted_legitimate_rps REAL,
                    current_capacity_rps REAL,
                    policy TEXT,
                    dry_run INTEGER NOT NULL DEFAULT 1,
                    shadow_mode INTEGER NOT NULL DEFAULT 1,
                    error_type TEXT,
                    error_message TEXT,
                    scaling_decision_json TEXT,
                    error_details_json TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_timestamp ON decision_history(timestamp DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_trace_id ON decision_history(trace_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_action ON decision_history(action);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_success ON decision_history(success);")
            conn.commit()

    def _row_to_model(self, row: sqlite3.Row) -> StoredObservation:
        action_val = row["action"]
        action_enum = ScalingAction(action_val) if action_val else None

        return StoredObservation(
            id=row["id"],
            trace_id=row["trace_id"],
            timestamp=row["timestamp"],
            completed_at=row["completed_at"],
            duration_ms=row["duration_ms"],
            success=bool(row["success"]),
            action=action_enum,
            reason=row["reason"],
            confidence=row["confidence"],
            recommended_pods=row["recommended_pods"],
            current_pods=row["current_pods"],
            baseline_hpa_recommended_pods=row["baseline_hpa_recommended_pods"],
            pod_delta_vs_baseline=row["pod_delta_vs_baseline"],
            traffic_risk=row["traffic_risk"],
            predicted_legitimate_rps=row["predicted_legitimate_rps"],
            current_capacity_rps=row["current_capacity_rps"],
            policy=row["policy"],
            dry_run=bool(row["dry_run"]),
            shadow_mode=bool(row["shadow_mode"]),
            error_type=row["error_type"],
            error_message=row["error_message"],
            scaling_decision_json=row["scaling_decision_json"],
            error_details_json=row["error_details_json"],
        )

    def record_observation(self, observation: StoredObservation) -> str:
        with self._lock:
            conn = self._get_connection()
            conn.execute("""
                INSERT INTO decision_history (
                    id, trace_id, timestamp, completed_at, duration_ms, success,
                    action, reason, confidence, recommended_pods, current_pods,
                    baseline_hpa_recommended_pods, pod_delta_vs_baseline,
                    traffic_risk, predicted_legitimate_rps, current_capacity_rps,
                    policy, dry_run, shadow_mode, error_type, error_message,
                    scaling_decision_json, error_details_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?
                )
            """, (
                observation.id,
                observation.trace_id,
                observation.timestamp,
                observation.completed_at,
                observation.duration_ms,
                1 if observation.success else 0,
                observation.action.value if observation.action else None,
                observation.reason,
                observation.confidence,
                observation.recommended_pods,
                observation.current_pods,
                observation.baseline_hpa_recommended_pods,
                observation.pod_delta_vs_baseline,
                observation.traffic_risk,
                observation.predicted_legitimate_rps,
                observation.current_capacity_rps,
                observation.policy,
                1 if observation.dry_run else 0,
                1 if observation.shadow_mode else 0,
                observation.error_type,
                observation.error_message,
                observation.scaling_decision_json,
                observation.error_details_json,
            ))
            conn.commit()

        logger.debug(
            f"Persisted observation '{observation.id}' (trace_id: {observation.trace_id}, success: {observation.success})",
            extra={"service": "platform", "trace_id": observation.trace_id},
        )
        return observation.id

    def get_observation(self, observation_id: str) -> Optional[StoredObservation]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("SELECT * FROM decision_history WHERE id = ?;", (observation_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_model(row)
        return None

    def get_by_trace_id(self, trace_id: str) -> List[StoredObservation]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT * FROM decision_history WHERE trace_id = ? ORDER BY timestamp DESC;",
                (trace_id,),
            )
            return [self._row_to_model(r) for r in cursor.fetchall()]

    def list_observations(
        self,
        limit: int = 50,
        offset: int = 0,
        success: Optional[bool] = None,
        action: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> List[StoredObservation]:
        query = "SELECT * FROM decision_history WHERE 1=1"
        params = []

        if success is not None:
            query += " AND success = ?"
            params.append(1 if success else 0)

        if action is not None:
            query += " AND action = ?"
            params.append(action)

        if trace_id is not None:
            query += " AND trace_id = ?"
            params.append(trace_id)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, tuple(params))
            return [self._row_to_model(r) for r in cursor.fetchall()]

    def get_observations_in_range(
        self,
        start_time: str,
        end_time: str,
        success: Optional[bool] = None,
        action: Optional[str] = None,
    ) -> List[StoredObservation]:
        query = "SELECT * FROM decision_history WHERE timestamp >= ? AND timestamp <= ?"
        params = [start_time, end_time]

        if success is not None:
            query += " AND success = ?"
            params.append(1 if success else 0)

        if action is not None:
            query += " AND action = ?"
            params.append(action)

        query += " ORDER BY timestamp ASC;"

        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, tuple(params))
            return [self._row_to_model(r) for r in cursor.fetchall()]

    def cleanup_old_observations(self, retention_days: int) -> int:
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_iso = cutoff_dt.isoformat()

        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("DELETE FROM decision_history WHERE timestamp < ?;", (cutoff_iso,))
            deleted_count = cursor.rowcount
            conn.commit()

        if deleted_count > 0:
            logger.info(
                f"Cleaned up {deleted_count} historical observations older than {retention_days} days (cutoff: {cutoff_iso})",
                extra={"service": "platform"},
            )
        return deleted_count

    def get_stats(self, retention_days: int = 7) -> HistoryStats:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed
                FROM decision_history;
            """)
            row = cursor.fetchone()
            total = row["total"] or 0
            successful = row["successful"] or 0
            failed = row["failed"] or 0

            return HistoryStats(
                total_observations=total,
                successful_observations=successful,
                failed_observations=failed,
                retention_days=retention_days,
            )

    def close(self) -> None:
        """Close the SQLite connection if open."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

