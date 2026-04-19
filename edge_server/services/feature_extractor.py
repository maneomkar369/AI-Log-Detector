"""
Feature Extractor — 72-Dimensional Behavioral Vector
======================================================
Extracts a feature vector from a batch of behavioral events collected
over a time window:

  Temporal   (24 dims) — Hour-of-day app usage distribution
  Sequential (28 dims) — Markov transition probabilities between top apps
    Interaction(20 dims) — Interaction + network + security/system summary signals
"""

import json
import math
from collections import Counter, defaultdict
from typing import List

import numpy as np

from config import settings


class FeatureExtractor:
    """
    Converts raw behavioral events into a fixed-size 72-dim feature vector.

    Usage::

        extractor = FeatureExtractor()
        vector = extractor.extract(events)
        # vector.shape == (72,)
    """

    TOP_K_APPS = 10  # Track transitions between top-10 most-used apps

    def extract(self, events: List[dict]) -> np.ndarray:
        """
        Extract a 72-dimensional feature vector from a list of events.

        Parameters
        ----------
        events : list[dict]
            Each event has keys: type, packageName, timestamp, data

        Returns
        -------
        np.ndarray
            Shape (72,) feature vector
        """
        temporal = self._extract_temporal(events)         # 24 dims
        sequential = self._extract_sequential(events)     # 28 dims
        interaction = self._extract_interaction(events)   # 20 dims

        vector = np.concatenate([temporal, sequential, interaction])
        assert vector.shape == (settings.feature_dim,), (
            f"Expected {settings.feature_dim} dims, got {vector.shape[0]}"
        )
        return vector

    # ────────────────────── Temporal Features (24) ──────────────────────

    def _extract_temporal(self, events: List[dict]) -> np.ndarray:
        """
        Hour-of-day app usage distribution.
        For each of the 24 hours, count how many events occurred.
        Returns a probability distribution (sums to 1).
        """
        hour_counts = np.zeros(24, dtype=np.float64)

        for ev in events:
            ts = ev.get("timestamp", 0)
            if ts > 0:
                # Timestamp is epoch millis
                from datetime import datetime, timezone
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                hour_counts[dt.hour] += 1

        total = hour_counts.sum()
        if total > 0:
            hour_counts /= total
        return hour_counts

    # ────────────────────── Sequential Features (28) ──────────────────

    def _extract_sequential(self, events: List[dict]) -> np.ndarray:
        """
        Markov transition probabilities between top-K apps.

        Layout (28 dims):
        - Top-K app frequency distribution (10 dims)
        - Top-K app transition entropy per source app (10 dims)
        - Overall transition probabilities for top 4 transitions (8 dims = 4×2)
        """
        app_events = [
            ev for ev in events
            if ev.get("event_type") in ("APP_USAGE", "app_usage")
            and ev.get("package_name")
        ]

        # Count app frequencies
        app_counts = Counter(ev["package_name"] for ev in app_events)
        top_apps = [app for app, _ in app_counts.most_common(self.TOP_K_APPS)]

        # App frequency distribution (10 dims)
        total_app = max(sum(app_counts.values()), 1)
        freq_dist = np.zeros(self.TOP_K_APPS, dtype=np.float64)
        for i, app in enumerate(top_apps):
            freq_dist[i] = app_counts[app] / total_app

        # Build transition matrix
        transitions = defaultdict(Counter)
        pkgs = [ev["package_name"] for ev in app_events]
        for i in range(len(pkgs) - 1):
            if pkgs[i] in top_apps and pkgs[i + 1] in top_apps:
                transitions[pkgs[i]][pkgs[i + 1]] += 1

        # Per-source transition entropy (10 dims)
        src_entropy = np.zeros(self.TOP_K_APPS, dtype=np.float64)
        for i, app in enumerate(top_apps):
            counts = transitions.get(app, {})
            total = sum(counts.values())
            if total > 0:
                probs = [c / total for c in counts.values()]
                src_entropy[i] = -sum(p * math.log2(p) for p in probs if p > 0)

        # Top-4 transition probabilities (8 dims: src_idx, dst_idx pairs)
        all_trans = []
        for src, dsts in transitions.items():
            for dst, c in dsts.items():
                all_trans.append((src, dst, c))
        all_trans.sort(key=lambda x: x[2], reverse=True)

        top_trans = np.zeros(8, dtype=np.float64)
        total_trans = max(sum(c for _, _, c in all_trans), 1)
        for i, (src, dst, c) in enumerate(all_trans[:4]):
            top_trans[i * 2] = top_apps.index(src) / self.TOP_K_APPS if src in top_apps else 0
            top_trans[i * 2 + 1] = c / total_trans

        return np.concatenate([freq_dist, src_entropy, top_trans])

    # ────────────────────── Interaction Features (20) ──────────────────

    def _extract_interaction(self, events: List[dict]) -> np.ndarray:
        """
        Interaction, network, and security/system features.

        Layout (20 dims):
        - Keystroke timing stats (5 dims): mean, std, min, max, count
        - Touch duration stats  (5 dims): mean, std, min, max, count
        - Swipe velocity stats  (5 dims): mean, std, min, max, count
        - Combined stats        (5 dims): total, interaction ratio,
                                         network signal,
                                         security ratio,
                                         burst/system signal
        """
        keystroke_times = []
        touch_durations = []
        swipe_velocities = []
        interaction_event_count = 0

        network_event_count = 0
        network_bytes = []

        security_event_count = 0

        system_event_count = 0
        system_state_samples = 0
        low_memory_count = 0
        battery_low_count = 0
        logcat_access_samples = 0
        logcat_restricted_count = 0

        for ev in events:
            data = self._parse_data(ev.get("data"))
            etype = str(ev.get("event_type", "")).upper()

            if etype in ("KEYSTROKE", "keystroke"):
                latency = data.get("latency", data.get("interval"))
                if latency is not None:
                    keystroke_times.append(float(latency))
                    interaction_event_count += 1

            elif etype in ("TOUCH", "touch"):
                dur = data.get("duration")
                if dur is not None:
                    touch_durations.append(float(dur))
                    interaction_event_count += 1

            elif etype in ("SWIPE", "swipe"):
                vel = data.get("velocity", data.get("speed"))
                if vel is not None:
                    swipe_velocities.append(float(vel))
                    interaction_event_count += 1

            elif etype in ("NETWORK_TRAFFIC", "NETWORK_APP"):
                network_event_count += 1
                rx = self._safe_float(data.get("rxBytesDelta"), default=0.0)
                tx = self._safe_float(data.get("txBytesDelta"), default=0.0)
                network_bytes.append(max(0.0, rx) + max(0.0, tx))

            elif etype.startswith("SECURITY_"):
                security_event_count += 1

            elif etype == "SYSTEM_STATE":
                system_event_count += 1
                system_state_samples += 1

                if bool(data.get("lowMemory", False)):
                    low_memory_count += 1

                battery_pct = self._safe_float(data.get("batteryPct"), default=-1.0)
                if 0 <= battery_pct <= 15:
                    battery_low_count += 1

            elif etype == "SYSTEM_LOGCAT_ACCESS":
                system_event_count += 1
                logcat_access_samples += 1
                status = str(data.get("status", "")).lower()
                if status in ("restricted", "error"):
                    logcat_restricted_count += 1

            elif etype.startswith("SYSTEM_"):
                system_event_count += 1

        def stat_block(values: list) -> np.ndarray:
            """Return [mean, std, min, max, count_normalized]."""
            if not values:
                return np.zeros(5, dtype=np.float64)
            arr = np.array(values, dtype=np.float64)
            return np.array([
                arr.mean(),
                arr.std(),
                arr.min(),
                arr.max(),
                min(len(arr) / 100.0, 1.0),  # Normalize count to [0, 1]
            ], dtype=np.float64)

        k_stats = stat_block(keystroke_times)
        t_stats = stat_block(touch_durations)
        s_stats = stat_block(swipe_velocities)

        # Combined stats (5 dims)
        total = max(len(events), 1)
        network_mb = sum(network_bytes) / (1024.0 * 1024.0)
        network_signal = min(1.0, (network_event_count / total) + min(network_mb / 10.0, 1.0) * 0.5)

        system_sample_count = max(system_state_samples + logcat_access_samples, 1)
        system_pressure = (low_memory_count + battery_low_count) / max(system_state_samples * 2, 1)
        logcat_restriction_ratio = logcat_restricted_count / system_sample_count
        system_signal = max(system_event_count / total, system_pressure, logcat_restriction_ratio)

        combined = np.array([
            min(total / 500.0, 1.0),  # Total events normalized
            interaction_event_count / total,
            network_signal,
            security_event_count / total,
            max(self._burstiness(events), system_signal),
        ], dtype=np.float64)

        return np.concatenate([k_stats, t_stats, s_stats, combined])

    @staticmethod
    def _parse_data(data):
        """Parse event payload into dict without raising."""
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                data = {}
        elif not isinstance(data, dict):
            data = {}
        return data

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        """Convert a value to float safely."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _burstiness(events: List[dict]) -> float:
        """Compute burstiness (std / mean of inter-arrival times)."""
        timestamps = sorted(
            ev.get("timestamp", 0) for ev in events if ev.get("timestamp")
        )
        if len(timestamps) < 2:
            return 0.0
        deltas = [timestamps[i + 1] - timestamps[i]
                  for i in range(len(timestamps) - 1)]
        mean_d = sum(deltas) / len(deltas)
        if mean_d == 0:
            return 0.0
        std_d = math.sqrt(sum((d - mean_d) ** 2 for d in deltas) / len(deltas))
        return std_d / mean_d
