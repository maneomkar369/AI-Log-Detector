"""
Baseline Manager — EMA Update + CUSUM Drift Detection
=======================================================
Maintains per-device adaptive behavioral baselines using:
- Exponential Moving Average (EMA) for online mean/covariance updates
- CUSUM algorithm to distinguish gradual drift from sudden anomalies
"""

from typing import Tuple

import numpy as np

from config import settings


class BaselineManager:
    """
    Manages per-device behavioral baselines.

    Lifecycle:
    1. Accumulation phase: Collect samples for `baseline_days` (7 days default)
    2. Baseline ready: Mean + covariance computed
    3. Adaptive update: Each new observation updates via EMA
    4. Drift detection: CUSUM flags sustained unidirectional changes
    """

    def __init__(self, learning_rate: float = None):
        self.alpha = learning_rate or settings.ema_learning_rate
        self.cusum_threshold = settings.cusum_threshold

    def initialize_baseline(
        self, samples: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Build the initial baseline from accumulated samples.

        Parameters
        ----------
        samples : np.ndarray
            Shape (N, 72) — N observations over the baseline period.

        Returns
        -------
        mean : np.ndarray, shape (72,)
        covariance : np.ndarray, shape (72, 72)
        """
        mean = np.mean(samples, axis=0)
        covariance = np.cov(samples, rowvar=False)

        # Regularize for small sample sizes
        if samples.shape[0] < samples.shape[1]:
            covariance += np.eye(samples.shape[1]) * 1e-4

        return mean, covariance

    def update_baseline(
        self,
        current_mean: np.ndarray,
        current_cov: np.ndarray,
        new_observation: np.ndarray,
        sample_count: int,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Update baseline using Exponential Moving Average (EMA).

        The learning rate decreases as more samples are collected,
        making the baseline more stable over time.

        Parameters
        ----------
        current_mean : np.ndarray, shape (72,)
        current_cov : np.ndarray, shape (72, 72)
        new_observation : np.ndarray, shape (72,)
        sample_count : int
            Total observations seen so far.

        Returns
        -------
        new_mean : np.ndarray
        new_cov : np.ndarray
        """
        # Adaptive learning rate (decreases with more data)
        alpha = self.alpha / (1 + sample_count / 1000.0)

        # EMA mean update
        new_mean = (1 - alpha) * current_mean + alpha * new_observation

        # EMA covariance update (rank-1 update)
        diff = (new_observation - current_mean).reshape(-1, 1)
        new_cov = (1 - alpha) * current_cov + alpha * (diff @ diff.T)

        return new_mean, new_cov

    def update_distance_stats(
        self,
        current_mean: float,
        current_std: float,
        new_distance: float,
        sample_count: int,
    ) -> Tuple[float, float]:
        """
        Update running mean and std of Mahalanobis distances using EMA.

        Parameters
        ----------
        current_mean, current_std : float
            Running distance statistics.
        new_distance : float
            Latest Mahalanobis distance.
        sample_count : int

        Returns
        -------
        new_mean, new_std : float
        """
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
    ) -> Tuple[float, float, bool]:
        """
        CUSUM drift detection.

        Accumulates positive and negative deviations from the expected
        distance. Triggers when either accumulator exceeds the threshold.

        Parameters
        ----------
        cusum_pos, cusum_neg : float
            Current CUSUM accumulators.
        distance : float
            Latest Mahalanobis distance.
        baseline_distance_mean : float
            Expected distance under normal behavior.

        Returns
        -------
        new_cusum_pos, new_cusum_neg : float
        drift_detected : bool
        """
        deviation = distance - baseline_distance_mean

        # Update CUSUM accumulators (reset to 0 if negative)
        new_pos = max(0.0, cusum_pos + deviation)
        new_neg = max(0.0, cusum_neg - deviation)

        drift_detected = (
            new_pos > self.cusum_threshold or
            new_neg > self.cusum_threshold
        )

        # Reset accumulators on drift detection
        if drift_detected:
            new_pos = 0.0
            new_neg = 0.0

        return float(new_pos), float(new_neg), drift_detected

    def should_update_after_anomaly(
        self, threat_type: str, severity: int
    ) -> bool:
        """
        Decide if the baseline should be updated after an anomaly.

        - USER_DRIFT: Yes — the user's behavior is genuinely changing.
        - Others: No — don't let attack data corrupt the baseline.
        """
        if threat_type == "USER_DRIFT" and severity < 5:
            return True
        return False
