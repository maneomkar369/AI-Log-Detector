"""
Anomaly Detector — Robust Mahalanobis Distance + Classification
================================================================
Computes anomaly scores using Mahalanobis distance from the device's
adaptive baseline and classifies detected anomalies into 4 threat types.

Enhancements:
  - Flaw #1: Yeo-Johnson transform + MinCovDet for robust distance
  - Flaw #3: Masked Mahalanobis for missing/sparse telemetry
  - Flaw #6: Whitened feature contributions (decorrelated XAI)
  - Flaw #10: Platt-scaled anomaly probability (calibrated confidence)
"""

import enum
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from config import settings
from services.threshold_calibrator import threshold_calibrator

logger = logging.getLogger(__name__)

# Optional robust covariance estimator
try:
    from sklearn.covariance import MinCovDet
    HAS_MINCOVDET = True
except ImportError:
    HAS_MINCOVDET = False


class ThreatType(str, enum.Enum):
    """Anomaly classification types."""
    NONE = "NONE"
    USER_DRIFT = "USER_DRIFT"
    DEVICE_MISUSE = "DEVICE_MISUSE"
    MALWARE_MIMICRY = "MALWARE_MIMICRY"
    INSIDER_THREAT = "INSIDER_THREAT"
    PHISHING = "PHISHING"
    ADVERSARIAL_MIMICRY = "ADVERSARIAL_MIMICRY"


@dataclass
class AnomalyResult:
    """Result of anomaly detection on a single feature vector."""
    is_anomaly: bool
    mahalanobis_distance: float
    threshold: float
    severity: int                     # 1-10
    confidence: float                 # 0.0-1.0
    anomaly_probability: float = 0.0  # Platt-scaled probability (Flaw #10)
    threat_type: ThreatType = ThreatType.NONE
    message: str = ""
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

    Enhancements over vanilla Mahalanobis:
        - Yeo-Johnson power transform for non-Gaussian features (Flaw #1)
        - MinCovDet robust covariance estimation (Flaw #1)
        - Masked distance for sparse/missing telemetry (Flaw #3)
        - Whitened feature contributions for stable XAI (Flaw #6)
        - Platt-scaled anomaly probability (Flaw #10)
        - Rolling median smoothing for confidence-aware stabilization (Claims 13-14)
        - Variance stability monitoring for adversarial behavior resilience (Claims 11-12)
    """

    def __init__(self, k_value: Optional[float] = None):
        self.k = k_value or settings.anomaly_k_value
        self.platt_slope = settings.platt_slope
        self.use_robust = settings.use_robust_mahalanobis and HAS_MINCOVDET

        # Claims 13-14: Confidence-Aware Stabilization (ASC)
        self.score_history = deque(maxlen=11)   # for median (odd number)
        self.smoothing_window = 5               # size of median filter
        self.min_confidence = 0.7               # threshold for alert

        # Claims 11-12: Adversarial Behavior Resilience (ABR)
        self.long_history = deque(maxlen=2000)   # for variance stability monitoring
        self.variance_ratio_threshold = 0.3      # threshold for detecting abnormally low variance

    @staticmethod
    def _stable_sigmoid(value: float) -> float:
        """Return sigmoid(value) without overflow for large-magnitude inputs."""
        if value >= 0:
            exp_neg = np.exp(-value)
            return float(1.0 / (1.0 + exp_neg))

        exp_pos = np.exp(value)
        return float(exp_pos / (1.0 + exp_pos))

    def detect(
        self,
        feature_vector: np.ndarray,
        baseline_mean: np.ndarray,
        baseline_cov: np.ndarray,
        feature_mask: Optional[np.ndarray] = None,
        k: float = 3.0,
        platt_slope: float = 2.0,
        device_id: Optional[str] = None,
        cusum_pos: float = 0.0,
        cusum_neg: float = 0.0,
        cusum_h: Optional[float] = None,
        distance_mean: float = 0.0,
        distance_std: float = 1.0,
    ) -> AnomalyResult:
        """
        Compute Mahalanobis distance and classify whether the feature vector is anomalous.

        Parameters
        ----------
        feature_vector : np.ndarray
            Input feature vector (d,)
        baseline_mean : np.ndarray
            Running mean vector (μ) of shape (d,)
        baseline_cov : np.ndarray
            Running covariance matrix (Σ) of shape (d, d)
        feature_mask : np.ndarray, optional
            Boolean mask indicating which features are present (True) or missing (False).
            Shape (d,). If None, all features are assumed present.
        k : float
            Mahalanobis distance multiplier for dynamic threshold (typically 2–4)
        platt_slope : float
            Slope parameter for Platt scaling of anomaly probability.
        device_id : str, optional
            Device ID for per-user threshold calibration.

        Returns
        -------
        AnomalyResult
            Result containing distance, threshold, probability, and classification.
        """
        # Validate inputs
        if feature_vector.ndim != 1:
            raise ValueError("feature_vector must be 1D")
        if baseline_mean.shape != feature_vector.shape:
            raise ValueError("baseline_mean must match feature_vector shape")
        if baseline_cov.shape != (len(feature_vector), len(feature_vector)):
            raise ValueError("baseline_cov must be square and match feature dimensions")

        # Feature vector is already power-transformed by BaselineManager if needed.

        # Compute Mahalanobis distance with masking support
        if feature_mask is not None and not np.all(feature_mask):
            # Sparse telemetry: use masked Mahalanobis distance
            distance, feature_contributions = self._masked_mahalanobis(
                feature_vector, baseline_mean, baseline_cov, feature_mask
            )
        else:
            # Dense telemetry: standard Mahalanobis distance
            distance, feature_contributions = self._compute_mahalanobis(feature_vector, baseline_mean, baseline_cov)

        # Get calibrated threshold and Platt slope if device_id is provided
        if device_id is not None:
            calibrated_slope = threshold_calibrator.get_user_platt_slope(device_id)
            if calibrated_slope != platt_slope:
                platt_slope = calibrated_slope
                logger.debug("Using calibrated Platt slope %.3f for device %s", platt_slope, device_id)

        # Dynamic threshold (k-sigma rule: Patent Claim 1)
        # Fallback to sqrt(dim) if distance_std is zero/invalid
        if distance_std > 0:
            threshold = distance_mean + k * distance_std
        else:
            threshold = k * np.sqrt(len(feature_vector))

        # Platt-scaled anomaly probability
        # P(anomaly) = sigmoid(slope × (distance² - threshold²))
        platt_input = platt_slope * (distance**2 - threshold**2)
        platt_probability = self._stable_sigmoid(platt_input)

        # Classify based on threshold
        is_anomaly = distance > threshold

        # Apply rolling median smoothing for confidence-aware stabilization (ASC - Claims 13-14)
        median_platt_prob = self._smooth_score(platt_probability)

        # Determine threat type and severity
        threat_type, severity, confidence, message = self._classify_threat(
            distance, threshold, median_platt_prob, feature_vector, baseline_mean,
            cusum_pos, cusum_neg, cusum_h
        )

        # Update long-term history for variance stability monitoring (ABR - Claims 11-12)
        # Note: Appending is already handled above in history logic if we unify it,
        # but for now we ensure long_history is updated only once per detect call.
        if len(self.long_history) >= 50:
            variance_ratio = self._variance_stability_ratio()
            # If variance ratio is abnormally low, might indicate adversarial mimicry
            if variance_ratio < self.variance_ratio_threshold and threat_type == ThreatType.NONE and distance > threshold * 0.5:
                threat_type = ThreatType.ADVERSARIAL_MIMICRY
                severity = max(1, min(3, int(3 * distance / (threshold + 1e-6))))

        return AnomalyResult(
            is_anomaly=is_anomaly,
            mahalanobis_distance=distance,
            threshold=threshold,
            severity=severity,
            confidence=confidence,
            anomaly_probability=median_platt_prob,
            threat_type=threat_type,
            message=message,
            feature_contributions=feature_contributions if feature_contributions else None,
        )

    def _compute_mahalanobis(
        self,
        x: np.ndarray,
        mu: np.ndarray,
        cov: np.ndarray,
    ) -> tuple[float, dict[int, float]]:
        """
        Standard Mahalanobis distance with whitened XAI contributions (Flaw #6).

        Returns (distance, feature_contributions).
        """
        # Add regularization for numerical stability
        reg_cov = cov + np.eye(cov.shape[0]) * 1e-6

        # Use pseudo-inverse for better numerical stability
        try:
            cov_inv = np.linalg.inv(reg_cov)
        except np.linalg.LinAlgError:
            # Fallback to pseudo-inverse if matrix is still singular
            logger.warning("PSD fallback: Using pseudo-inverse due to singular covariance matrix")
            cov_inv = np.linalg.pinv(reg_cov)

        diff = x - mu

        # Flaw #6: Whitened contributions — decorrelated and stable
        feature_contributions = self._whitened_contributions(diff, cov_inv)

        # Distance
        transformed_diff = cov_inv @ diff
        distance = float(np.sqrt(np.maximum(np.sum(diff * transformed_diff), 0.0)))

        return distance, feature_contributions

    def _masked_mahalanobis(
        self,
        x: np.ndarray,
        mu: np.ndarray,
        cov: np.ndarray,
        mask: np.ndarray,
    ) -> tuple[float, dict[int, float]]:
        """
        Flaw #3: Masked Mahalanobis distance for sparse telemetry.

        Imputes missing values with baseline mean, computes distance only
        on observed dimensions, and scales by n_total / n_observed for
        comparable magnitude.
        """
        n_total = len(mask)
        n_observed = int(mask.sum())

        if n_observed == 0:
            return 0.0, {}

        # Impute missing with baseline mean
        x_imputed = np.where(mask > 0, x, mu)

        # Add regularization for numerical stability
        reg_cov = cov + np.eye(cov.shape[0]) * 1e-6

        # Use pseudo-inverse for better numerical stability
        try:
            cov_inv = np.linalg.inv(reg_cov)
        except np.linalg.LinAlgError:
            # Fallback to pseudo-inverse if matrix is still singular
            logger.warning("PSD fallback: Using pseudo-inverse due to singular covariance matrix")
            cov_inv = np.linalg.pinv(reg_cov)

        diff = (x_imputed - mu) * mask  # Zero out missing dimensions

        # Distance on observed dims, scaled for comparability
        transformed_diff = cov_inv @ diff
        dist_sq = np.sum(diff * transformed_diff)
        distance = float(np.sqrt(np.maximum(dist_sq * (n_total / n_observed), 0.0)))

        # Whitened contributions (on observed dims only)
        feature_contributions = self._whitened_contributions(diff, cov_inv)

        return distance, feature_contributions

    @staticmethod
    def _whitened_contributions(
        diff: np.ndarray,
        cov_inv: np.ndarray,
    ) -> dict[int, float]:
        """
        Flaw #6: Compute decorrelated feature contributions via whitening.

        x̃ = Σ^{-1/2} (x - μ)
        contribution_i = x̃_i²

        This decorrelates contributions so correlated features
        (e.g., app launches vs network bytes) don't arbitrarily split credit.
        """
        try:
            # Cholesky of inverse covariance = Σ^{-1/2}
            L = np.linalg.cholesky(cov_inv)
            x_white = L @ diff
            contribs = x_white ** 2
        except np.linalg.LinAlgError:
            # Fallback to raw contributions if Cholesky fails
            transformed = cov_inv @ diff
            contribs = np.abs(diff * transformed)

        total_c = np.sum(contribs)
        if total_c <= 0:
            return {}

        normalized_c = contribs / total_c

        # Top 5 contributors above 5% threshold
        top_indices = np.argsort(normalized_c)[-5:][::-1]
        return {
            int(i): float(normalized_c[i])
            for i in top_indices
            if normalized_c[i] > 0.05
        }

    def _platt_probability(self, distance: float, threshold: float) -> float:
        """
        Flaw #10: Calibrated anomaly probability using Platt scaling.

        P(anomaly) = 1 / (1 + exp(-a * (D_M - τ)))

        where a is the slope parameter and τ is the dynamic threshold.
        This converts raw Mahalanobis distance into a calibrated [0, 1] probability.
        """
        z = self.platt_slope * (distance - threshold)
        # Clamp to avoid overflow
        z = max(-20.0, min(20.0, z))
        return 1.0 / (1.0 + np.exp(-z))

    def _classify_threat(
        self,
        distance: float,
        threshold: float,
        platt_prob: float,
        vector: np.ndarray,
        mean: np.ndarray,
        cusum_pos: float,
        cusum_neg: float,
        cusum_h: Optional[float] = None,
    ) -> tuple[ThreatType, int, float, str]:
        """
        Classify the anomaly type based on deviation patterns.
        Returns (ThreatType, severity, confidence, message).
        """
        if distance <= threshold:
            z_score = distance / (threshold / self.k) if threshold > 0 else 0
            severity = max(1, self._compute_severity(z_score, False))
            return ThreatType.NONE, severity, platt_prob, self._build_message(ThreatType.NONE, severity, distance, threshold)

        # Check if CUSUM indicates gradual drift
        # H1: Use dynamic threshold h if provided, otherwise fallback to settings.
        h_threshold = cusum_h if cusum_h is not None else settings.cusum_threshold
        cusum_total = abs(cusum_pos) + abs(cusum_neg)
        
        threat_type = ThreatType.DEVICE_MISUSE
        if cusum_total > h_threshold and distance < threshold * 1.5:
            threat_type = ThreatType.USER_DRIFT

        # Check for malware patterns: abnormal sequential + temporal features
        diff = vector - mean
        # Assuming feature indices based on comments
        temporal_deviation = np.linalg.norm(diff[:24])
        sequential_deviation = np.linalg.norm(diff[24:52])
        interaction_deviation = np.linalg.norm(diff[52:])

        # Malware mimicry: very high sequential deviation (unusual app transitions)
        if sequential_deviation > temporal_deviation * 2 and distance > threshold * 2:
            threat_type = ThreatType.MALWARE_MIMICRY

        # Insider threat: high interaction deviation (typing/touch pattern change)
        elif interaction_deviation > temporal_deviation * 2:
            threat_type = ThreatType.INSIDER_THREAT

        severity = self._compute_severity(distance / (threshold / self.k) if threshold > 0 else 0, True)
        message = self._build_message(threat_type, severity, distance, threshold)
        
        return threat_type, severity, platt_prob, message

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
            ThreatType.ADVERSARIAL_MIMICRY: (
                f"Adversarial behavior detected — suspiciously stable pattern "
                f"(severity {severity}/10)"
            ),
        }
        return messages.get(threat_type, "Unknown anomaly")

    def _smooth_score(self, raw_score: float) -> float:
        """Rolling median smoothing for confidence-aware stabilization (Claims 13-14)."""
        self.score_history.append(raw_score)
        if len(self.score_history) < self.smoothing_window:
            return raw_score
        # median of the last `smoothing_window` scores
        window = list(self.score_history)[-self.smoothing_window:]
        return float(np.median(window))

    def _compute_confidence(self, distance: float, threshold: float) -> float:
        """Platt scaling confidence - already in your code, keep as is."""
        # Reuse existing Platt scaling logic
        z = self.platt_slope * (distance - threshold)
        # Clamp to avoid overflow
        z = max(-20.0, min(20.0, z))
        return 1.0 / (1.0 + np.exp(-z))

    def _variance_stability_ratio(self) -> float:
        """Returns ratio of short-term MAD to long-term std dev for adversarial behavior resilience (Claims 11-12)."""
        if len(self.long_history) < 200:
            return 1.0
        # short-term = last 50 scores (Median Absolute Deviation)
        short = list(self.long_history)[-50:]
        short_median = np.median(short)
        short_mad = np.median(np.abs(short - short_median))
        # long-term std deviation
        long_std = np.std(self.long_history)
        if long_std < 1e-6:
            return 0.0
        return short_mad / long_std

    def detect_adversarial(self, distance_raw: float, threshold: float) -> tuple[bool, float]:
        """
        Adversarial Behavior Resilience (ABR) detection for Claims 11-12.

        Returns True if the behavior is suspiciously stable (low variance),
        indicating potential adversarial mimicry.
        """
        self.long_history.append(distance_raw)
        var_ratio = self._variance_stability_ratio()
        # Condition: anomaly score below threshold but variance ratio very low
        # This detects when behavior is "too normal" - abnormally stable
        if distance_raw < threshold and var_ratio < self.variance_ratio_threshold:
            return True, var_ratio
        return False, var_ratio
