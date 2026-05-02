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
from typing import Any, Dict, List, Optional
import numpy as np

from sqlalchemy.ext.asyncio import AsyncSession

from models.alert import Alert

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
                     "quarantine_app", "uninstall_app", "lock_device"],
    }

    def create_alert(
        self,
        device_id: str,
        severity: int,
        threat_type: str,
        message: str,
        confidence: float,
        mahalanobis_distance: float = 0.0,
        anomaly_probability: float = 0.0,
        target_package: Optional[str] = None,
        target_uid: Optional[int] = None,
        xai_explanation: Optional[Dict[str, Any]] = None,
        feature_vector: Optional[np.ndarray] = None,
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
        anomaly_probability : float (0-1)
            Platt-scaled calibrated probability (Flaw #10).

        Returns
        -------
        Alert (unsaved)
        """
        # Determine recommended actions based on severity
        if severity <= 3:
            action_names = self.SEVERITY_ACTIONS["low"]
        elif severity <= 6:
            action_names = self.SEVERITY_ACTIONS["medium"]
        elif severity <= 8:
            action_names = self.SEVERITY_ACTIONS["high"]
        else:
            action_names = self.SEVERITY_ACTIONS["critical"]

        actions = self._build_action_plan(
            action_names=action_names,
            target_package=target_package,
            target_uid=target_uid,
        )

        alert = Alert(
            anomaly_id=f"alt_{uuid.uuid4().hex[:8]}",
            device_id=device_id,
            severity=severity,
            threat_type=threat_type,
            message=message,
            confidence=confidence,
            mahalanobis_distance=mahalanobis_distance,
            xai_explanation=json.dumps(xai_explanation) if xai_explanation else None,
            feature_vector=json.dumps(feature_vector.tolist()) if feature_vector is not None else None,
            actions=json.dumps(actions),
            status="pending",
            anomaly_probability=anomaly_probability,
            created_at=datetime.utcnow(),
        )

        logger.info(
            "Alert created: %s | device=%s severity=%d type=%s prob=%.3f",
            alert.anomaly_id, device_id, severity, threat_type, anomaly_probability,
        )
        return alert

    async def save_alert(self, db: AsyncSession, alert: Alert) -> Alert:
        """Persist an alert to the database."""
        db.add(alert)
        await db.flush()
        return alert

    def alert_to_ws_message(self, alert: Alert) -> str:
        """Serialize an alert for WebSocket delivery to the device."""
        explanation = self._parse_json_object(alert.xai_explanation)
        anomaly_prob = alert.anomaly_probability
        return json.dumps({
            "type": "alert",
            "anomalyId": alert.anomaly_id,
            "anomaly_id": alert.anomaly_id,
            "deviceId": alert.device_id,
            "device_id": alert.device_id,
            "severity": alert.severity,
            "threatType": alert.threat_type,
            "threat_type": alert.threat_type,
            "message": alert.message,
            "confidence": alert.confidence,
            "anomalyProbability": round(anomaly_prob, 4),
            "anomaly_probability": round(anomaly_prob, 4),
            "actions": json.loads(alert.actions) if alert.actions else [],
            "xaiExplanation": explanation,
            "xai_explanation": explanation,
            "status": alert.status,
            "createdAt": alert.created_at.isoformat() if alert.created_at else None,
            "respondedAt": alert.responded_at.isoformat() if alert.responded_at else None,
        })

    @staticmethod
    def _parse_json_object(raw: Optional[str]) -> Dict[str, Any]:
        """Parse a JSON object payload and return empty dict when invalid."""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _build_action_plan(
        self,
        action_names: List[str],
        target_package: Optional[str] = None,
        target_uid: Optional[int] = None,
    ) -> List[dict[str, Any]]:
        """Build an action plan with per-action target metadata when available."""
        plan: List[dict[str, Any]] = []

        for action_name in action_names:
            item: dict[str, Any] = {"name": action_name}

            if action_name in {"kill_process", "quarantine_app", "uninstall_app"}:
                if not target_package:
                    continue
                item["targetPackage"] = target_package

            if action_name == "block_network":
                if target_uid is None:
                    continue
                item["targetUid"] = int(target_uid)

            plan.append(item)

        return plan

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

    async def mark_normal_alert(
        self, db: AsyncSession, alert_id: str
    ) -> Optional[Alert]:
        """Mark an alert as 'Normal' (User Correction Loop - Flaw #26)."""
        from sqlalchemy import select
        result = await db.execute(
            select(Alert).where(Alert.anomaly_id == alert_id)
        )
        alert = result.scalar_one_or_none()
        if alert:
            alert.status = "normal"
            alert.responded_at = datetime.utcnow()
            logger.info("Alert %s marked as normal (user correction)", alert_id)
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

    async def delete_all_alerts(self, db: AsyncSession, device_id: str) -> int:
        """Delete all alerts for a device."""
        from sqlalchemy import delete
        result = await db.execute(
            delete(Alert).where(Alert.device_id == device_id)
        )
        return result.rowcount
