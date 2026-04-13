"""
REST API Routes
================
HTTP endpoints for the dashboard and external integrations.
"""

import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.database import get_db
from models.alert import Alert
from models.device import Device
from services.alert_manager import AlertManager
from services.action_executor import ActionExecutor

router = APIRouter(prefix="/api", tags=["API"])

alert_manager = AlertManager()
action_executor = ActionExecutor()


# ────────────────── Alert Endpoints ──────────────────

@router.get("/alerts/{device_id}")
async def get_device_alerts(
    device_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List recent alerts for a device."""
    alerts = await alert_manager.get_device_alerts(db, device_id, limit)
    return [
        {
            "anomalyId": a.anomaly_id,
            "severity": a.severity,
            "threatType": a.threat_type,
            "message": a.message,
            "confidence": a.confidence,
            "mahalanobisDistance": a.mahalanobis_distance,
            "actions": json.loads(a.actions) if a.actions else [],
            "status": a.status,
            "createdAt": a.created_at.isoformat() if a.created_at else None,
            "respondedAt": a.responded_at.isoformat() if a.responded_at else None,
        }
        for a in alerts
    ]


@router.post("/alerts/{alert_id}/approve")
async def approve_alert(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
):
    """User approves neutralization for an alert."""
    alert = await alert_manager.approve_alert(db, alert_id)
    if not alert:
        raise HTTPException(404, f"Alert {alert_id} not found")

    # Execute approved actions
    actions = json.loads(alert.actions) if alert.actions else []
    results = await action_executor.execute_all_actions(
        actions=actions,
        device_id=alert.device_id,
    )
    alert.action_executed = True
    alert.action_result = json.dumps(results)
    await db.commit()

    return {
        "status": "approved",
        "anomalyId": alert.anomaly_id,
        "actionsExecuted": results,
    }


@router.post("/alerts/{alert_id}/deny")
async def deny_alert(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
):
    """User denies action for an alert."""
    alert = await alert_manager.deny_alert(db, alert_id)
    if not alert:
        raise HTTPException(404, f"Alert {alert_id} not found")
    await db.commit()
    return {"status": "denied", "anomalyId": alert.anomaly_id}


# ────────────────── Device Stats ──────────────────

@router.get("/stats/{device_id}")
async def get_device_stats(
    device_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get behavioral statistics for a device."""
    result = await db.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(404, f"Device {device_id} not found")

    # Count alerts by status
    from sqlalchemy import func
    alert_counts = await db.execute(
        select(Alert.status, func.count(Alert.id))
        .where(Alert.device_id == device_id)
        .group_by(Alert.status)
    )
    status_counts = {row[0]: row[1] for row in alert_counts}

    return {
        "deviceId": device.id,
        "deviceName": device.name,
        "model": device.model,
        "androidVersion": device.android_version,
        "baselineSamples": device.baseline_sample_count,
        "distanceMean": round(device.distance_mean, 4),
        "distanceStd": round(device.distance_std, 4),
        "cusumPos": round(device.cusum_pos, 4),
        "cusumNeg": round(device.cusum_neg, 4),
        "isActive": device.is_active,
        "firstSeen": device.first_seen.isoformat() if device.first_seen else None,
        "lastSeen": device.last_seen.isoformat() if device.last_seen else None,
        "alertCounts": status_counts,
    }


# ────────────────── Health Check ──────────────────

@router.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "behavioral-anomaly-detector"}
