"""
Tests for Feature Extractor
=============================
"""

import numpy as np
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.feature_extractor import FeatureExtractor


@pytest.fixture
def extractor():
    return FeatureExtractor()


@pytest.fixture
def sample_events():
    """Generate a realistic batch of behavioral events."""
    events = []
    base_ts = 1700000000000  # epoch millis

    # APP_USAGE events across different hours
    apps = [
        "com.whatsapp", "com.instagram", "com.chrome",
        "com.spotify", "com.gmail", "com.slack",
    ]
    for i in range(30):
        events.append({
            "event_type": "APP_USAGE",
            "package_name": apps[i % len(apps)],
            "timestamp": base_ts + i * 60000,  # 1 minute apart
            "data": '{"totalTime": 120, "count": 3}',
        })

    # KEYSTROKE events
    for i in range(20):
        events.append({
            "event_type": "KEYSTROKE",
            "package_name": "com.whatsapp",
            "timestamp": base_ts + 30 * 60000 + i * 500,
            "data": f'{{"latency": {50 + i * 2}}}',
        })

    # TOUCH events
    for i in range(15):
        events.append({
            "event_type": "TOUCH",
            "package_name": "com.instagram",
            "timestamp": base_ts + 40 * 60000 + i * 1000,
            "data": f'{{"duration": {100 + i * 10}}}',
        })

    # SWIPE events
    for i in range(10):
        events.append({
            "event_type": "SWIPE",
            "package_name": "com.instagram",
            "timestamp": base_ts + 50 * 60000 + i * 2000,
            "data": f'{{"velocity": {500 + i * 50}}}',
        })

    return events


def test_extract_returns_correct_shape(extractor, sample_events):
    """Feature vector must be exactly 72 dimensions."""
    vector = extractor.extract(sample_events)
    assert isinstance(vector, np.ndarray)
    assert vector.shape == (72,)


def test_extract_temporal_sums_to_one(extractor, sample_events):
    """Temporal features (hour distribution) should sum to ~1.0."""
    vector = extractor.extract(sample_events)
    temporal = vector[:24]
    assert abs(temporal.sum() - 1.0) < 0.01  # Allow small float error


def test_extract_empty_events(extractor):
    """Empty event list should return zero vector."""
    vector = extractor.extract([])
    assert vector.shape == (72,)
    # Should be mostly zeros
    assert np.allclose(vector, 0.0, atol=0.01)


def test_extract_no_interaction_events(extractor):
    """Events with no interaction data should have zero interaction features."""
    events = [{
        "event_type": "APP_USAGE",
        "package_name": "com.test",
        "timestamp": 1700000000000 + i * 60000,
        "data": "{}",
    } for i in range(10)]

    vector = extractor.extract(events)
    interaction = vector[52:]  # Last 20 dims
    assert np.allclose(interaction[:15], 0.0, atol=0.01)  # k, t, s stats


def test_extract_values_are_finite(extractor, sample_events):
    """All feature values must be finite (no NaN or Inf)."""
    vector = extractor.extract(sample_events)
    assert np.all(np.isfinite(vector))
