"""
Anomaly Detector — Mahalanobis Distance + Classification
=========================================================
Computes anomaly scores using Mahalanobis distance from the device's
adaptive baseline and classifies detected anomalies into 4 threat types.
"""

import enum
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.spatial.distance import mahalanobis as scipy_mahalanobis

from config import settings


class ThreatType(str, enum.Enum):
    """Anomaly classification types."""
    NONE = "NONE"
    USER_DRIFT = "USER_DRIFT"
    DEVICE_MISUSE = "DEVICE_MISUSE"
    MALWARE_MIMICRY = "MALWARE_MIMICRY"
    INSIDER_THREAT = "INSIDER_THREAT"
    PHISHING = "PHISHING"


@dataclass
class AnomalyResult:
    """Result of anomaly detection on a single feature vector."""
    is_anomaly: bool
    mahalanobis_distance: float
    threshold: float
    severity: int                     # 1-10
    confidence: float                 # 0.0-1.0
    threat_type: ThreatType
    message: str
    feature_contributions: Optional[dict[int, float]] = None


class AnomalyDetector:
    """
    Detects anomalies using Mahalanobis distance with dynamic thresholding.

    The detector compares a new feature vector against the device's
    behavioral baseline (mean μ, covariance Σ) and checks if the
    Mahalanobis distance exceeds a dynamic threshold.

    Anomaly scoring:
        D = √[(x - μ)ᵀ Σ⁻¹ (x - μ)]
        Threshold T = μ_D + k · σ_D
    """

    def __init__(self, k_value: Optional[float] = None):
        self.k = k_value or settings.anomaly_k_value

    def detect(
        self,
        feature_vector: np.ndarray,
        baseline_mean: np.ndarray,
        baseline_cov: np.ndarray,
        distance_mean: float = 0.0,
        distance_std: float = 1.0,
        cusum_pos: float = 0.0,
        cusum_neg: float = 0.0,
    ) -> AnomalyResult:
        """
        Evaluate a feature vector against the baseline.

        Parameters
        ----------
        feature_vector : np.ndarray
            Current 72-dim observation.
        baseline_mean : np.ndarray
            Running mean (μ) of past observations.
        baseline_cov : np.ndarray
            Running covariance matrix (Σ).
        distance_mean : float
            Running mean of past Mahalanobis distances.
        distance_std : float
            Running std of past Mahalanobis distances.
        cusum_pos, cusum_neg : float
            CUSUM statistics for drift detection.

        Returns
        -------
        AnomalyResult
        """
        # Regularize covariance to prevent singularity
        reg_cov = baseline_cov + np.eye(baseline_cov.shape[0]) * 1e-6

        try:
            # Compute inverse for Mahalanobis distance
            cov_inv = np.linalg.inv(reg_cov)
            diff = feature_vector - baseline_mean
            
            # Distance squared is diff^T @ inv_cov @ diff
            # Feature contribution approximation: | diff * (inv_cov @ diff) |
            transformed_diff = cov_inv @ diff
            contribs = np.abs(diff * transformed_diff)
            total_c = np.sum(contribs)
            
            feature_contributions = {}
            if total_c > 0:
                normalized_c = contribs / total_c
                # Top 5 indices
                top_indices = np.argsort(normalized_c)[-5:][::-1]
                feature_contributions = {int(i): float(normalized_c[i]) for i in top_indices if normalized_c[i] > 0.05}
                
            distance = float(np.sqrt(np.sum(diff * transformed_diff)))
        except np.linalg.LinAlgError:
            # Fallback to Euclidean if covariance is degenerate
            distance = float(np.linalg.norm(feature_vector - baseline_mean))
            feature_contributions = {}

        # Dynamic threshold
        threshold = distance_mean + self.k * max(distance_std, 0.1)
        is_anomaly = distance > threshold

        # Classify threat type
        threat_type = self._classify_threat(
            feature_vector, baseline_mean, distance,
            threshold, cusum_pos, cusum_neg
        )

        # Compute severity (1-10)
        if distance_std > 0:
            z_score = (distance - distance_mean) / max(distance_std, 0.1)
        else:
            z_score = distance
        severity = self._compute_severity(z_score, is_anomaly)

        # Confidence based on how far past threshold
        if is_anomaly and threshold > 0:
            confidence = min((distance - threshold) / threshold + 0.5, 1.0)
        elif is_anomaly:
            confidence = 0.7
        else:
            confidence = max(0.0, 1.0 - distance / max(threshold, 1.0))

        message = self._build_message(threat_type, severity, distance, threshold)

        return AnomalyResult(
            is_anomaly=is_anomaly,
            mahalanobis_distance=distance,
            threshold=threshold,
            severity=severity,
            confidence=round(confidence, 3),
            threat_type=threat_type,
            message=message,
            feature_contributions=feature_contributions if 'feature_contributions' in locals() else None,
        )

    def _classify_threat(
        self, vector: np.ndarray, mean: np.ndarray,
        distance: float, threshold: float,
        cusum_pos: float, cusum_neg: float,
    ) -> ThreatType:
        """
        Classify the anomaly type based on deviation patterns.

        - USER_DRIFT      — gradual change (CUSUM triggered but distance moderate)
        - DEVICE_MISUSE   — sudden, extreme deviation
        - MALWARE_MIMICRY — specific feature pattern (high app transitions, bursts)
        - INSIDER_THREAT  — sensitive interaction pattern shift
        """
        if distance <= threshold:
            return ThreatType.NONE

        # Check if CUSUM indicates gradual drift
        cusum_total = abs(cusum_pos) + abs(cusum_neg)
        if cusum_total > settings.cusum_threshold and distance < threshold * 1.5:
            return ThreatType.USER_DRIFT

        # Check for malware patterns: abnormal sequential + temporal features
        diff = vector - mean
        temporal_deviation = np.linalg.norm(diff[:24])
        sequential_deviation = np.linalg.norm(diff[24:52])
        interaction_deviation = np.linalg.norm(diff[52:])

        # Malware mimicry: very high sequential deviation (unusual app transitions)
        if sequential_deviation > temporal_deviation * 2 and distance > threshold * 2:
            return ThreatType.MALWARE_MIMICRY

        # Insider threat: high interaction deviation (typing/touch pattern change)
        if interaction_deviation > temporal_deviation * 2:
            return ThreatType.INSIDER_THREAT

        # Default for sudden large deviation
        return ThreatType.DEVICE_MISUSE

    @staticmethod
    def _compute_severity(z_score: float, is_anomaly: bool) -> int:
        """Map z-score to 1-10 severity."""
        if not is_anomaly:
            return max(1, min(3, int(z_score + 1)))
        if z_score < 4:
            return 5
        elif z_score < 6:
            return 7
        elif z_score < 8:
            return 8
        else:
            return min(10, int(z_score) + 1)

    @staticmethod
    def _build_message(
        threat_type: ThreatType, severity: int,
        distance: float, threshold: float,
    ) -> str:
        """Human-readable alert message."""
        messages = {
            ThreatType.NONE: "Normal behavior detected",
            ThreatType.USER_DRIFT: (
                f"Gradual behavioral drift detected "
                f"(distance {distance:.1f} vs threshold {threshold:.1f})"
            ),
            ThreatType.DEVICE_MISUSE: (
                f"Sudden behavioral deviation detected — possible device misuse "
                f"(severity {severity}/10)"
            ),
            ThreatType.MALWARE_MIMICRY: (
                f"Suspicious app transition pattern — possible malware "
                f"(distance {distance:.1f}, {severity}/10 severity)"
            ),
            ThreatType.INSIDER_THREAT: (
                f"Unusual interaction patterns — possible unauthorized user "
                f"(severity {severity}/10)"
            ),
        }
        return messages.get(threat_type, "Unknown anomaly")
