from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Optional
import numpy as np

logger = logging.getLogger("traffic-intelligence")

# Path to serialized model artifact
_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "weights" / "isolation_forest.joblib"


@dataclass(frozen=True)
class MLAnomalyResult:
    is_available: bool
    is_anomaly: bool
    anomaly_score: float  # Normalized to [0.0, 1.0], higher = more anomalous
    raw_decision_score: float  # Raw IsolationForest decision_function output
    signal_tag: Optional[str] = None


class IsolationForestAnomalyDetector:
    """
    Unsupervised ML Anomaly Detector using Isolation Forest.
    Evaluates 7-dimensional normalized feature vectors extracted from telemetry.
    Safely falls back if model weights are unavailable or fail to load.
    """

    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = model_path or _MODEL_PATH
        self.model = None
        self._load_model()

    def _load_model(self) -> None:
        if self.model_path.exists():
            try:
                import joblib
                self.model = joblib.load(self.model_path)
                logger.info(f"Loaded Isolation Forest model from {self.model_path}")
            except Exception as e:
                logger.warning(f"Failed to load Isolation Forest model from {self.model_path}: {e}")
                self.model = None
        else:
            logger.info(f"Isolation Forest weights not found at {self.model_path}; running in rule-only mode")
            self.model = None

    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    def detect(
        self,
        features_dict: dict
    ) -> MLAnomalyResult:
        if not self.is_loaded:
            return MLAnomalyResult(
                is_available=False,
                is_anomaly=False,
                anomaly_score=0.0,
                raw_decision_score=0.0,
                signal_tag=None,
            )

        try:
            # 7-dimensional feature vector
            vector = np.array([[
                float(features_dict.get("total_rps", 0.0)),
                float(features_dict.get("burst_ratio", 1.0)),
                float(features_dict.get("error_rate", 0.0)),
                float(features_dict.get("ip_concentration", 0.0)),
                float(features_dict.get("ua_anomaly_ratio", 0.0)),
                float(features_dict.get("single_endpoint_ratio", 0.0)),
                float(features_dict.get("data_completeness", 0.0)),
            ]], dtype=np.float32)

            # decision_function: typically ranges roughly [-0.5, 0.5]
            # Higher = normal (inlier), Lower = anomalous (outlier)
            raw_score = float(self.model.decision_function(vector)[0])
            pred = int(self.model.predict(vector)[0])  # 1 = inlier, -1 = outlier

            # Map raw score to normalized anomaly score in [0.0, 1.0]
            # When raw_score is around 0.15+ -> very normal -> anomaly_score ~ 0.0
            # When raw_score is around -0.25 -> highly anomalous -> anomaly_score ~ 1.0
            # Sigmoid/logistic or linear clamping:
            # normalized_anomaly = 1.0 - clip((raw_score + 0.25) / 0.45, 0.0, 1.0)
            normalized_normal = max(0.0, min(1.0, (raw_score + 0.20) / 0.40))
            anomaly_score = round(1.0 - normalized_normal, 3)

            is_anomaly = (pred == -1) or (anomaly_score >= 0.60)
            signal = "ml_anomaly_detected" if is_anomaly else None

            return MLAnomalyResult(
                is_available=True,
                is_anomaly=is_anomaly,
                anomaly_score=anomaly_score,
                raw_decision_score=round(raw_score, 4),
                signal_tag=signal,
            )
        except Exception as e:
            logger.warning(f"Error during Isolation Forest inference: {e}")
            return MLAnomalyResult(
                is_available=False,
                is_anomaly=False,
                anomaly_score=0.0,
                raw_decision_score=0.0,
                signal_tag=None,
            )
