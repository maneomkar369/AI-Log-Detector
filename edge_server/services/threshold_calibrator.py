"""
Threshold Calibrator
====================
Provides adaptive threshold calibration for anomaly detection.
"""

import logging
import numpy as np
from typing import List, Optional
from collections import deque
from dataclasses import dataclass
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Result of threshold calibration."""
    optimal_threshold: float
    platt_slope: float
    calibration_score: float  # Cross-validation score


class ThresholdCalibrator:
    """
    Adaptive threshold calibrator that adjusts anomaly detection parameters
    based on user-specific data patterns.
    
    Implements per-user Platt slope calibration as described in Flaw #10.
    """

    def __init__(self, calibration_window_days: int = 3):
        """
        Initialize the threshold calibrator.
        
        Parameters
        ----------
        calibration_window_days : int
            Number of days of user data to use for calibration (default: 3)
        """
        self.calibration_window_days = calibration_window_days
        self.user_calibrations = {}  # user_id -> CalibrationResult
        self.default_platt_slope = settings.platt_slope

    def calibrate_for_user(
        self, 
        user_id: str, 
        validation_scores: List[float], 
        validation_labels: List[bool],
        min_samples: int = 100
    ) -> CalibrationResult:
        """
        Calibrate threshold parameters for a specific user.
        
        Parameters
        ----------
        user_id : str
            Unique identifier for the user/device
        validation_scores : List[float]
            Historical anomaly scores for calibration
        validation_labels : List[bool]
            Ground truth labels (True = actual anomaly, False = normal)
        min_samples : int
            Minimum number of samples required for calibration
            
        Returns
        -------
        CalibrationResult
            Optimal calibration parameters for this user
        """
        # Check if we have enough data for calibration
        if len(validation_scores) < min_samples:
            logger.info(
                "Insufficient data for user %s calibration: %d/%d samples", 
                user_id, len(validation_scores), min_samples
            )
            # Return default calibration
            return CalibrationResult(
                optimal_threshold=self._calculate_default_threshold(),
                platt_slope=self.default_platt_slope,
                calibration_score=0.0
            )

        try:
            # Convert to numpy arrays
            scores = np.array(validation_scores).reshape(-1, 1)
            labels = np.array(validation_labels)
            
            # Standardize scores for better numerical stability
            scaler = StandardScaler()
            scores_scaled = scaler.fit_transform(scores)
            
            # Fit logistic regression to learn optimal parameters
            lr = LogisticRegression()
            lr.fit(scores_scaled, labels)
            
            # Extract coefficients for Platt scaling
            # The logistic regression gives us: P(y=1) = 1/(1 + exp(-(A*x + B)))
            # We want: P(y=1) = 1/(1 + exp(-slope*(x - threshold)))
            # So: slope = A, threshold = -B/A
            
            A = lr.coef_[0][0]
            B = lr.intercept_[0]
            
            if abs(A) < 1e-10:  # Avoid division by zero
                slope = self.default_platt_slope
                threshold = self._calculate_default_threshold()
            else:
                slope = A
                threshold = -B / A
            
            # Calculate cross-validation score as quality metric
            from sklearn.model_selection import cross_val_score
            cv_scores = cross_val_score(lr, scores_scaled, labels, cv=5)
            calibration_score = cv_scores.mean()
            
            # Store calibration result
            result = CalibrationResult(
                optimal_threshold=float(threshold),
                platt_slope=float(slope),
                calibration_score=float(calibration_score)
            )
            
            self.user_calibrations[user_id] = result
            
            logger.info(
                "User %s calibrated: threshold=%.3f, slope=%.3f, score=%.3f", 
                user_id, threshold, slope, calibration_score
            )
            
            return result
            
        except Exception as e:
            logger.warning(
                "Calibration failed for user %s: %s. Using defaults.", 
                user_id, str(e)
            )
            return CalibrationResult(
                optimal_threshold=self._calculate_default_threshold(),
                platt_slope=self.default_platt_slope,
                calibration_score=0.0
            )

    def get_user_platt_slope(self, user_id: str) -> float:
        """
        Get the calibrated Platt slope for a specific user.
        
        Parameters
        ----------
        user_id : str
            Unique identifier for the user/device
            
        Returns
        -------
        float
            Calibrated Platt slope for this user, or default if not calibrated
        """
        if user_id in self.user_calibrations:
            return self.user_calibrations[user_id].platt_slope
        return self.default_platt_slope

    def get_user_threshold(self, user_id: str) -> float:
        """
        Get the calibrated threshold for a specific user.
        
        Parameters
        ----------
        user_id : str
            Unique identifier for the user/device
            
        Returns
        -------
        float
            Calibrated threshold for this user, or default if not calibrated
        """
        if user_id in self.user_calibrations:
            return self.user_calibrations[user_id].optimal_threshold
        return self._calculate_default_threshold()

    def _calculate_default_threshold(self) -> float:
        """
        Calculate default threshold based on configuration.
        
        Returns
        -------
        float
            Default threshold value
        """
        # Default k-value based threshold (similar to existing implementation)
        return 3.0 * np.sqrt(72)  # Assuming 72-dimensional feature space

    def clear_user_calibration(self, user_id: str) -> None:
        """
        Clear calibration data for a specific user.
        
        Parameters
        ----------
        user_id : str
            Unique identifier for the user/device
        """
        if user_id in self.user_calibrations:
            del self.user_calibrations[user_id]
            logger.info("Cleared calibration for user %s", user_id)


# Global instance
threshold_calibrator = ThresholdCalibrator()
