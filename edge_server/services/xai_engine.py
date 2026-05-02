"""
XAI Engine — Explainable AI for Anomaly Alerts
================================================
Translates raw feature contributions into human-readable explanations.

Enhancement (Flaw #6):
  - compute_whitened_contributions() — decorrelated, stable contributions
    using Σ^{-1/2} whitening so correlated features don't split credit
  - Temporal aggregation — report top-3 features across last N anomalous
    windows instead of per-window noise
"""

import logging
from collections import defaultdict
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def compute_whitened_contributions(
    x: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
) -> dict[int, float]:
    try:
        reg_cov = cov + np.eye(cov.shape[0]) * 1e-6
        L = np.linalg.cholesky(reg_cov)   # Σ = L L^T
        diff = x - mu
        # Solve L z = diff  ->  z = L^{-1} diff (whitened)
        z = np.linalg.solve(L, diff)
        contribs = z ** 2
    except np.linalg.LinAlgError:
        # Fallback to raw contributions
        diff = x - mu
        reg_cov = cov + np.eye(cov.shape[0]) * 1e-6
        try:
            cov_inv = np.linalg.inv(reg_cov)
            transformed = cov_inv @ diff
            contribs = np.abs(diff * transformed)
        except np.linalg.LinAlgError:
            return {}

    total = np.sum(contribs)
    if total <= 0:
        return {}
    normalized = contribs / total
    top_indices = np.argsort(normalized)[-5:][::-1]
    return {
        int(i): float(normalized[i])
        for i in top_indices
        if normalized[i] > 0.05
    }


class TemporalXAIAggregator:
    """
    Flaw #6: Aggregate XAI explanations over time.

    Instead of reporting per-window contributions (which are noisy),
    accumulate contributions across the last N anomalous windows and
    report the consistently top-3 features.
    """

    def __init__(self, window_size: int = 5):
        self.window_size = window_size
        # device_id → list of contribution dicts
        self._history: dict[str, list[dict[int, float]]] = defaultdict(list)

    def add(self, device_id: str, contributions: dict[int, float]) -> None:
        """Record contributions from an anomalous window."""
        history = self._history[device_id]
        history.append(contributions)
        if len(history) > self.window_size:
            history.pop(0)

    def get_aggregated(self, device_id: str) -> dict[int, float]:
        """
        Return averaged contributions across last N anomalous windows.

        Features that consistently appear as top contributors are
        more reliable explanations than one-off spikes.
        """
        history = self._history.get(device_id, [])
        if not history:
            return {}

        # Sum contributions across windows
        totals: dict[int, float] = defaultdict(float)
        counts: dict[int, int] = defaultdict(int)

        for window_contribs in history:
            for idx, weight in window_contribs.items():
                totals[idx] += weight
                counts[idx] += 1

        # Average and filter
        n_windows = len(history)
        averaged = {
            idx: totals[idx] / n_windows
            for idx in totals
            if counts[idx] >= max(1, n_windows // 2)  # Present in ≥50% of windows
        }

        # Normalize
        total = sum(averaged.values())
        if total <= 0:
            return {}

        normalized = {idx: v / total for idx, v in averaged.items()}

        # Top 3
        sorted_items = sorted(normalized.items(), key=lambda x: x[1], reverse=True)
        return {idx: weight for idx, weight in sorted_items[:3] if weight > 0.05}


# Shared aggregator instance
_temporal_aggregator = TemporalXAIAggregator(window_size=5)


def record_anomaly_contributions(device_id: str, contributions: dict[int, float]) -> None:
    """Record contributions from an anomalous window for temporal aggregation."""
    _temporal_aggregator.add(device_id, contributions)


def get_aggregated_contributions(device_id: str) -> dict[int, float]:
    """Get temporally aggregated contributions for a device."""
    return _temporal_aggregator.get_aggregated(device_id)


def explain_feature_contributions(feature_contributions: dict) -> list[str]:
    """
    Translates raw Mahalanobis feature contribution indices into human-readable explanations.
    
    Feature Vector Layout (72 dims total):
    - [0:24] Temporal: Hour-of-day usage distribution.
    - [24:34] Sequential: Top-K app frequency distribution.
    - [34:44] Sequential: App transition entropy.
    - [44:52] Sequential: Top transition probabilities.
    - [52:57] Interaction: Keystroke timing stats.
    - [57:62] Interaction: Touch duration stats.
    - [62:67] Interaction: Swipe velocity stats.
    - [67:72] Interaction: Combined/Network/Security stats.
    """
    if not feature_contributions:
        return []

    explanations = []
    
    # Sort contributions by value descending
    sorted_features = sorted(feature_contributions.items(), key=lambda x: x[1], reverse=True)
    
    for idx, weight in sorted_features:
        pct = weight * 100
        if pct < 5.0:
            continue
            
        idx = int(idx)
        if 0 <= idx < 24:
            explanations.append(f"Highly unusual device activity around {idx}:00 (contributed {pct:.1f}% to anomaly score).")
        elif 24 <= idx < 34:
            explanations.append(f"Abnormal frequency of specific app usage (contributed {pct:.1f}%).")
        elif 34 <= idx < 44:
            explanations.append(f"Unusual app switching behavior / transition entropy (contributed {pct:.1f}%).")
        elif 44 <= idx < 52:
            explanations.append(f"Unexpected opening sequence between apps (contributed {pct:.1f}%).")
        elif 52 <= idx < 57:
            explanations.append(f"Anomalous keystroke dynamics detected (contributed {pct:.1f}%).")
        elif 57 <= idx < 62:
            explanations.append(f"Atypical touch durations (possible automation or fatigue) (contributed {pct:.1f}%).")
        elif 62 <= idx < 67:
            explanations.append(f"Irregular swipe velocities (contributed {pct:.1f}%).")
        elif 67 <= idx < 72:
            explanations.append(f"Deviant network, security, or global interaction properties (contributed {pct:.1f}%).")
            
    return explanations
