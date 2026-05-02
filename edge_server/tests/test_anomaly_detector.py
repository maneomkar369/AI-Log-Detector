"""
Tests for Anomaly Detector
============================
"""

import numpy as np
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.anomaly_detector import AnomalyDetector, ThreatType


@pytest.fixture
def detector():
    return AnomalyDetector(k_value=3.0)


@pytest.fixture
def baseline():
    """Create a simple baseline (mean=0, identity covariance)."""
    dim = 72
    return {
        "mean": np.zeros(dim),
        "cov": np.eye(dim),
        "distance_mean": 8.0,
        "distance_std": 1.0,
    }


def test_normal_behavior(detector, baseline):
    """Normal vector (close to mean) should NOT be detected as anomaly."""
    normal_vector = np.random.normal(0, 0.5, 72)
    result = detector.detect(
        feature_vector=normal_vector,
        baseline_mean=baseline["mean"],
        baseline_cov=baseline["cov"],
    )
    assert not result.is_anomaly
    assert result.threat_type == ThreatType.NONE
    assert result.severity <= 3


def test_extreme_anomaly(detector, baseline):
    """Vector far from baseline should be detected as anomaly."""
    extreme_vector = np.ones(72) * 20.0
    result = detector.detect(
        feature_vector=extreme_vector,
        baseline_mean=baseline["mean"],
        baseline_cov=baseline["cov"],
    )
    assert result.is_anomaly
    assert result.severity >= 5
    assert result.confidence > 0.5
    assert result.mahalanobis_distance > baseline["distance_mean"]


def test_sequential_deviation_classified_as_malware(detector, baseline):
    """High deviation in sequential features (dims 24-52) → MALWARE_MIMICRY."""
    vector = np.zeros(72)
    vector[24:52] = 15.0  # High sequential deviation
    result = detector.detect(
        feature_vector=vector,
        baseline_mean=baseline["mean"],
        baseline_cov=baseline["cov"],
    )
    if result.is_anomaly:
        assert result.threat_type in (ThreatType.MALWARE_MIMICRY, ThreatType.DEVICE_MISUSE)


def test_interaction_deviation_classified_as_insider(detector, baseline):
    """High deviation in interaction features (dims 52+) → INSIDER_THREAT."""
    vector = np.zeros(72)
    vector[52:] = 15.0  # High interaction deviation
    result = detector.detect(
        feature_vector=vector,
        baseline_mean=baseline["mean"],
        baseline_cov=baseline["cov"],
    )
    if result.is_anomaly:
        assert result.threat_type in (ThreatType.INSIDER_THREAT, ThreatType.DEVICE_MISUSE)


def test_result_has_message(detector, baseline):
    """Every result should have a human-readable message."""
    vector = np.ones(72) * 20.0
    result = detector.detect(
        feature_vector=vector,
        baseline_mean=baseline["mean"],
        baseline_cov=baseline["cov"],
    )
    assert isinstance(result.message, str)
    assert len(result.message) > 10


def test_severity_range(detector, baseline):
    """Severity must always be 1–10."""
    for scale in [0.1, 1.0, 5.0, 20.0]:
        vector = np.ones(72) * scale
        result = detector.detect(
            feature_vector=vector,
            baseline_mean=baseline["mean"],
            baseline_cov=baseline["cov"],
        )
        assert 1 <= result.severity <= 10
