"""
BehaviorEvent Model
====================
Stores raw behavioral events received from Android devices.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, Text, BigInteger, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from services.crypto_manager import crypto_manager

logger = logging.getLogger(__name__)


class BehaviorEvent(Base):
    """A single behavioral event from an Android device."""

    __tablename__ = "behavior_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("devices.id"), index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    package_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # epoch millis
    data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # encrypted JSON
    received_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )

    @property
    def decrypted_data(self) -> Optional[str]:
        """Return decrypted data, or None if decryption fails or data is None."""
        if self.data is None:
            return None
        try:
            return crypto_manager.decrypt(self.data)
        except Exception as e:
            logger.error("Failed to decrypt data for event %d: %s", self.id, e)
            return None

    @property
    def decrypted_package_name(self) -> Optional[str]:
        """Return decrypted package name, or None if decryption fails or package_name is None."""
        if self.package_name is None:
            return None
        try:
            # If the package_name is not encrypted (e.g., older rows), decrypt will fallback?
            # In our crypto_manager, decryption without encryption key raises error.
            # We assume all new rows are encrypted; old ones would need migration.
            return crypto_manager.decrypt(self.package_name)
        except Exception as e:
            logger.error("Failed to decrypt package name for event %d: %s", self.id, e)
            return None

    def __repr__(self) -> str:
        # Safely use decrypted value or fallback to encrypted preview
        pkg = self.decrypted_package_name
        if pkg is None:
            pkg = "<encrypted>" if self.package_name else None
        return (
            f"<BehaviorEvent id={self.id} device={self.device_id!r} "
            f"type={self.event_type!r} pkg={pkg!r}>"
        )