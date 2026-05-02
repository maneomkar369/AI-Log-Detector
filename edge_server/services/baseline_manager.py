"""
Baseline Manager — EMA Update + Self-Tuning CUSUM Drift Detection
===================================================================
Maintains per-device adaptive behavioral baselines using:
- Exponential Moving Average (EMA) for online mean/covariance updates
- Self-tuning CUSUM algorithm to distinguish gradual drift from sudden anomalies (Flaw #2)
- Yeo-Johnson transform parameter tracking for robust distance (Flaw #1)
"""

import logging
from collections import deque
from typing import Optional, Tuple, Dict

import numpy as np

from config import settings

logger = logging.getLogger(__name__)

# Optional Yeo-Johnson transform (Flaw #1)
try:
    from sklearn.preprocessing import PowerTransformer
    HAS_POWER_TRANSFORM = True
except ImportError:
    HAS_POWER_TRANSFORM = False

# Default refit interval if not set in settings
YEO_JOHNSON_REFIT_INTERVAL = getattr(settings, 'yeo_johnson_refit_interval', 1000)


class SelfTuningCUSUM:
    """
    Flaw #2: Self-tuning CUSUM drift detector.

    Parameters δ (allowance) and h (threshold) are derived from the rolling
    standard deviation of the Mahalanobis distance history:

        δ = c₁ · σ_D
        h = c₂ · σ_D

    This adapts to per-user activity variance.
    """

    def __init__(
        self,
        window: int = 1000,
        c1: float = 0.5,
        c2: float = 5.0,
    ):
        self.window = window
        self.c1 = c1
        self.c2 = c2
        self.scores: deque = deque(maxlen=window)
        self.S_pos = 0.0
        self.S_neg = 0.0

    def update(
        self,
        distance: float,
        baseline_distance_mean: float,
    ) -> Tuple[float, float, bool]:
        """
        Update CUSUM accumulators with a new distance observation.

        Returns (cusum_pos, cusum_neg, drift_detected)
        """
        self.scores.append(distance)

        if len(self.scores) > 10:
            sigma = float(np.std(list(self.scores)))
        else:
            sigma = 1.0

        delta = self.c1 * max(sigma, 0.01)
        h = self.c2 * max(sigma, 0.01)

        deviation = distance - baseline_distance_mean

        self.S_pos = max(0.0, self.S_pos + (deviation - delta))
        self.S_neg = max(0.0, self.S_neg + (-deviation - delta))

        drift_detected = self.S_pos > h or self.S_neg > h

        if drift_detected:
            self.S_pos = 0.0
            self.S_neg = 0.0

        return float(self.S_pos), float(self.S_neg), drift_detected, float(h)


class BaselineManager:
    """
    Manages per-device behavioral baselines with online EMA, drift detection,
    and optional Yeo‑Johnson transformation.
    """

    def __init__(self, learning_rate: float = None):
        self.alpha = learning_rate or settings.ema_learning_rate
        self.cusum_threshold = settings.cusum_threshold
        self._cusum_instances: Dict[str, SelfTuningCUSUM] = {}
        self._sample_buffers: Dict[str, deque] = {}

        # Flaw #1: per‑device Yeo‑Johnson transformers (fitted on baseline samples)
        self._power_transformers: Dict[str, Optional[PowerTransformer]] = {}

    def get_cusum(self, device_id: str) -> SelfTuningCUSUM:
        """Get or create a self-tuning CUSUM instance for a device."""
        if device_id not in self._cusum_instances:
            self._cusum_instances[device_id] = SelfTuningCUSUM(
                window=settings.cusum_window,
                c1=settings.cusum_c1,
                c2=settings.cusum_c2,
            )
        return self._cusum_instances[device_id]

    def get_warm_start_baseline(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return pre‑trained generic baseline (mean, cov) for new devices."""
        import os
        import json
        filepath = os.path.join("data", "generic_baseline.json")
        default_dim = settings.feature_dim
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                generic_mean = np.array(data["baseline_mean"])
                generic_cov = np.array(data["baseline_covariance"])
                if generic_mean.shape[0] != default_dim:
                    raise ValueError(f"Dimension mismatch: expected {default_dim}")
        except Exception as e:
            logger.warning(f"Could not load {filepath}, using zero‑state matrix: {e}")
            generic_mean = np.zeros(default_dim)
            generic_cov = np.eye(default_dim)
        return generic_mean, generic_cov

    def get_blended_baseline(
        self,
        device_first_seen,
        personalized_mean: Optional[np.ndarray],
        personalized_cov: Optional[np.ndarray],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Patent Claim: Baseline Blending.
        - First 24h: 100% generic baseline.
        - Next 7 days: monotonically decrease generic weight to 0.
        - After 8 days: 100% personalised baseline.
        """
        from datetime import datetime, timezone

        generic_mean, generic_cov = self.get_warm_start_baseline()

        if personalized_mean is None or personalized_cov is None:
            return generic_mean, generic_cov

        now = datetime.utcnow()
        if device_first_seen.tzinfo is not None:
            now = now.replace(tzinfo=timezone.utc)

        age_seconds = max(0.0, (now - device_first_seen).total_seconds())
        warmup_seconds = 24.0 * 3600.0
        blending_seconds = 7.0 * 24.0 * 3600.0

        if age_seconds <= warmup_seconds:
            alpha = 1.0
        elif age_seconds < warmup_seconds + blending_seconds:
            progress = (age_seconds - warmup_seconds) / blending_seconds
            alpha = 1.0 - progress
        else:
            alpha = 0.0

        effective_mean = alpha * generic_mean + (1.0 - alpha) * personalized_mean
        effective_cov = alpha * generic_cov + (1.0 - alpha) * personalized_cov

        # Claim 9: ensure PSD
        effective_cov = self._ensure_psd(effective_cov, generic_cov)

        return effective_mean, effective_cov

    @staticmethod
    def _ensure_psd(cov: np.ndarray, fallback_cov: np.ndarray, eps: float = 1e-6) -> np.ndarray:
        """
        Ensure covariance matrix is positive semi‑definite.
        First attempt: add small diagonal regularization.
        If still not PSD, fallback to generic baseline.
        """
        try:
            np.linalg.cholesky(cov)
            return cov
        except np.linalg.LinAlgError:
            # Try regularizing
            reg_cov = cov + eps * np.eye(cov.shape[0])
            try:
                np.linalg.cholesky(reg_cov)
                logger.warning("Covariance not PSD – added regularization (eps=%.1e)", eps)
                return reg_cov
            except np.linalg.LinAlgError:
                logger.warning("Covariance still not PSD after regularization – falling back to generic baseline")
                return fallback_cov

    def fit_power_transform(self, samples: np.ndarray, device_id: str) -> None:
        """
        Flaw #1: Fit Yeo-Johnson transform on baseline samples and store per device.
        """
        if not HAS_POWER_TRANSFORM or not settings.use_yeo_johnson_transform:
            self._power_transformers[device_id] = None
            return
        if samples.ndim != 2 or samples.shape[0] < 2:
            logger.warning("Insufficient samples for power transform fitting (need at least 2 rows)")
            self._power_transformers[device_id] = None
            return
        try:
            pt = PowerTransformer(method='yeo-johnson', standardize=False)
            pt.fit(samples)
            self._power_transformers[device_id] = pt
            logger.info("Yeo-Johnson transform fitted for device %s on %d samples", device_id, samples.shape[0])
        except Exception as exc:
            logger.warning("Failed to fit Yeo-Johnson transform for device %s: %s", device_id, exc)
            self._power_transformers[device_id] = None

    def apply_power_transform(self, device_id: str, feature_vector: np.ndarray) -> np.ndarray:
        """
        Apply the stored Yeo-Johnson transform to a feature vector.
        If no transform is stored, return the original vector.
        """
        pt = self._power_transformers.get(device_id)
        if pt is None or not settings.use_yeo_johnson_transform:
            return feature_vector
        try:
            # PowerTransformer expects 2D input (n_samples, n_features)
            if feature_vector.ndim == 1:
                transformed = pt.transform(feature_vector.reshape(1, -1))
                return transformed.reshape(-1)
            else:
                # Already 2D (batch)
                return pt.transform(feature_vector)
        except Exception as e:
            logger.warning("Power transform failed for device %s: %s", device_id, e)
            return feature_vector

    def update_baseline(
        self,
        current_mean: np.ndarray,
        current_cov: np.ndarray,
        new_observation: np.ndarray,
        sample_count: int,
        drift_detected: bool = False,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        EMA update using CORRECT covariance formula (outer product of diff_old and diff_new).
        """
        alpha = self.alpha / (1 + sample_count / 1000.0)

        # Claim 2c: temporary boost on drift
        if drift_detected:
            alpha = min(alpha * 5.0, 0.5)

        diff_old = new_observation - current_mean
        new_mean = (1 - alpha) * current_mean + alpha * new_observation
        diff_new = new_observation - new_mean

        # Correct covariance update
        new_cov = (1 - alpha) * current_cov + alpha * np.outer(diff_old, diff_new)

        # Enforce symmetry (mitigate floating point drift)
        new_cov = (new_cov + new_cov.T) * 0.5

        return new_mean, new_cov

    def update_distance_stats(
        self,
        current_mean: float,
        current_std: float,
        new_distance: float,
        sample_count: int,
    ) -> Tuple[float, float]:
        """Update running mean and std of Mahalanobis distances using EMA."""
        alpha = self.alpha / (1 + sample_count / 500.0)
        new_mean = (1 - alpha) * current_mean + alpha * new_distance
        deviation = (new_distance - current_mean) ** 2
        new_var = (1 - alpha) * (current_std ** 2) + alpha * deviation
        new_std = np.sqrt(max(new_var, 1e-8))
        return float(new_mean), float(new_std)

    def update_cusum(
        self,
        cusum_pos: float,
        cusum_neg: float,
        distance: float,
        baseline_distance_mean: float,
        device_id: Optional[str] = None,
    ) -> Tuple[float, float, bool]:
        """CUSUM drift detection – uses self‑tuning version if device_id provided."""
        if device_id is not None:
            cusum = self.get_cusum(device_id)
            cusum.S_pos = cusum_pos
            cusum.S_neg = cusum_neg
            return cusum.update(distance, baseline_distance_mean)

        # Legacy fixed‑threshold fallback
        deviation = distance - baseline_distance_mean
        new_pos = max(0.0, cusum_pos + deviation)
        new_neg = max(0.0, cusum_neg - deviation)
        drift = new_pos > self.cusum_threshold or new_neg > self.cusum_threshold
        if drift:
            new_pos, new_neg = 0.0, 0.0
        return new_pos, new_neg, drift

    def should_update_after_anomaly(self, threat_type: str, severity: int) -> bool:
        """Allow baseline update only for genuine behavioural drift."""
        return threat_type == "USER_DRIFT" and severity < 5

    def add_to_refit_buffer(self, device_id: str, sample: np.ndarray):
        """Buffer samples for periodic Yeo-Johnson refit."""
        if device_id not in self._sample_buffers:
            self._sample_buffers[device_id] = deque(maxlen=YEO_JOHNSON_REFIT_INTERVAL)
        self._sample_buffers[device_id].append(sample)

    def should_refit(self, device_id: str, sample_count: int) -> bool:
        """Check if it's time to refit the Yeo-Johnson transform."""
        return sample_count > 0 and sample_count % YEO_JOHNSON_REFIT_INTERVAL == 0

    def get_buffer_samples(self, device_id: str) -> Optional[np.ndarray]:
        """Return buffered samples as a 2D array, or None if insufficient."""
        buf = self._sample_buffers.get(device_id)
        if buf and len(buf) >= 100:
            # Ensure all samples have the same shape and convert to numpy
            try:
                return np.array(list(buf))
            except Exception as e:
                logger.warning("Failed to convert buffer to array for device %s: %s", device_id, e)
                return None
        return None