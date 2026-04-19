"""
BehaviorEvent Model
====================
Stores raw behavioral events received from Android devices.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Text, BigInteger, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class BehaviorEvent(Base):
    """A single behavioral event from an Android device."""

    __tablename__ = "behavior_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("devices.id"), index=True
    )

    # Event classification
    event_type: Mapped[str] = mapped_column(String(32))
    # Types: APP_USAGE, KEYSTROKE, TOUCH, LOCATION, NETWORK, ACCESSIBILITY

    package_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    timestamp: Mapped[int] = mapped_column(BigInteger)  # epoch millis from device
    data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON payload

    # Server-side metadata
    received_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    def __repr__(self) -> str:
        return (
            f"<BehaviorEvent id={self.id} device={self.device_id!r} "
            f"type={self.event_type!r} pkg={self.package_name!r}>"
        )
