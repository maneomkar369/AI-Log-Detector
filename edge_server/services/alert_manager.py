"""
Alert Manager
==============
Creates alert records, pushes them to devices via WebSocket,
and optionally sends FCM push notifications.
"""

import json
import uuid
import logging
from datetime import datetime
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from models.alert import Alert
from config import settings

logger = logging.getLogger(__name__)


class AlertManager:
    """Manages alert lifecycle: create → push → respond → execute."""

    SEVERITY_ACTIONS = {
        # severity ≤ 3 → log only
        "low": [],
        # severity 4–6 → notify user
        "medium": ["notify"],
        # severity 7–8 → notify + suggest actions
        "high": ["notify", "kill_process", "block_network"],
        # severity 9–10 → notify + auto-escalate if no response
        "critical": ["notify", "kill_process", "block_network",
                     "quarantine_app", "lock_device"],
    }

    def create_alert(
        self,
        device_id: str,
        severity: int,
        threat_type: str,
        message: str,
        confidence: float,
        mahalanobis_distance: float = 0.0,
    ) -> Alert:
        """
        Create a new Alert object (not yet persisted).

        Parameters
        ----------
        device_id : str
        severity : int (1-10)
        threat_type : str (USER_DRIFT, DEVICE_MISUSE, etc.)
        message : str
        confidence : float (0-1)
        mahalanobis_distance : float

        Returns
        -------
        Alert (unsaved)
        """
        # Determine recommended actions based on severity
        if severity <= 3:
            actions = self.SEVERITY_ACTIONS["low"]
        elif severity <= 6:
            actions = self.SEVERITY_ACTIONS["medium"]
        elif severity <= 8:
            actions = self.SEVERITY_ACTIONS["high"]
        else:
            actions = self.SEVERITY_ACTIONS["critical"]

        alert = Alert(
            anomaly_id=f"alt_{uuid.uuid4().hex[:8]}",
            device_id=device_id,
            severity=severity,
            threat_type=threat_type,
            message=message,
            confidence=confidence,
            mahalanobis_distance=mahalanobis_distance,
            actions=json.dumps(actions),
            status="pending",
            created_at=datetime.utcnow(),
        )

        logger.info(
            "Alert created: %s | device=%s severity=%d type=%s",
            alert.anomaly_id, device_id, severity, threat_type,
        )
        return alert

    async def save_alert(self, db: AsyncSession, alert: Alert) -> Alert:
        """Persist an alert to the database."""
        db.add(alert)
        await db.flush()
        return alert

    def alert_to_ws_message(self, alert: Alert) -> str:
        """Serialize an alert for WebSocket delivery to the device."""
        return json.dumps({
            "type": "alert",
            "anomalyId": alert.anomaly_id,
            "severity": alert.severity,
            "threatType": alert.threat_type,
            "message": alert.message,
            "confidence": alert.confidence,
            "actions": json.loads(alert.actions) if alert.actions else [],
        })

    async def approve_alert(
        self, db: AsyncSession, alert_id: str
    ) -> Optional[Alert]:
        """Mark an alert as approved by the user."""
        from sqlalchemy import select
        result = await db.execute(
            select(Alert).where(Alert.anomaly_id == alert_id)
        )
        alert = result.scalar_one_or_none()
        if alert:
            alert.status = "approved"
            alert.responded_at = datetime.utcnow()
            logger.info("Alert %s approved", alert_id)
        return alert

    async def deny_alert(
        self, db: AsyncSession, alert_id: str
    ) -> Optional[Alert]:
        """Mark an alert as denied by the user."""
        from sqlalchemy import select
        result = await db.execute(
            select(Alert).where(Alert.anomaly_id == alert_id)
        )
        alert = result.scalar_one_or_none()
        if alert:
            alert.status = "denied"
            alert.responded_at = datetime.utcnow()
            logger.info("Alert %s denied", alert_id)
        return alert

    async def get_device_alerts(
        self, db: AsyncSession, device_id: str, limit: int = 50
    ) -> List[Alert]:
        """Retrieve recent alerts for a device."""
        from sqlalchemy import select
        result = await db.execute(
            select(Alert)
            .where(Alert.device_id == device_id)
            .order_by(Alert.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
