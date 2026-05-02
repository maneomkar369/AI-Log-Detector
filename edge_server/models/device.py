"""
Device Model
=============
Tracks registered Android devices, their behavioral baselines,
and connection metadata.
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Text, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Device(Base):
    """Registered Android device with adaptive behavioral baseline."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="Unknown Device")
    android_version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Behavioral baseline (stored as JSON-serialized numpy arrays)
    baseline_mean: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    baseline_covariance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    baseline_sample_count: Mapped[int] = mapped_column(Integer, default=0)

    # Distance tracking for dynamic threshold
    distance_mean: Mapped[float] = mapped_column(Float, default=0.0)
    distance_std: Mapped[float] = mapped_column(Float, default=1.0)

    # CUSUM state
    cusum_pos: Mapped[float] = mapped_column(Float, default=0.0)
    cusum_neg: Mapped[float] = mapped_column(Float, default=0.0)

    # Metadata
    first_seen: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    # Flaw #25: Time Zone Shift Tracking
    last_tz_offset: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tz_shift_active_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def set_baseline_mean(self, arr) -> None:
        """Serialize a numpy array / list to JSON for storage."""
        self.baseline_mean = json.dumps(arr.tolist() if hasattr(arr, "tolist") else arr)

    def get_baseline_mean(self):
        """Deserialize baseline mean from JSON."""
        if self.baseline_mean:
            import numpy as np
            return np.array(json.loads(self.baseline_mean))
        return None

    def set_baseline_covariance(self, arr) -> None:
        """Serialize covariance matrix to JSON."""
        self.baseline_covariance = json.dumps(
            arr.tolist() if hasattr(arr, "tolist") else arr
        )

    def get_baseline_covariance(self):
        """Deserialize covariance matrix from JSON."""
        if self.baseline_covariance:
            import numpy as np
            return np.array(json.loads(self.baseline_covariance))
        return None

    def __repr__(self) -> str:
        return f"<Device id={self.id!r} name={self.name!r} samples={self.baseline_sample_count}>"
