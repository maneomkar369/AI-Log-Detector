"""
WebSocket Connection Handler
==============================
Manages active WebSocket connections from Android devices,
parses incoming behavioral events, and routes them through
the analysis pipeline.
"""

import json
import logging
from datetime import datetime
from typing import Dict

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from models.database import async_session
from models.device import Device
from models.behavior_event import BehaviorEvent
from services.feature_extractor import FeatureExtractor
from services.anomaly_detector import AnomalyDetector
from services.baseline_manager import BaselineManager
from services.alert_manager import AlertManager
from services.redis_buffer import RedisBuffer

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Tracks active WebSocket connections per device and manages
    the full analysis pipeline:
    event ingestion → buffering → feature extraction → anomaly detection → alerting
    """

    def __init__(self, redis_buffer: RedisBuffer):
        self.active_connections: Dict[str, WebSocket] = {}
        self.redis = redis_buffer
        self.feature_extractor = FeatureExtractor()
        self.anomaly_detector = AnomalyDetector()
        self.baseline_manager = BaselineManager()
        self.alert_manager = AlertManager()

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        """Accept a new device connection."""
        await websocket.accept()
        self.active_connections[device_id] = websocket

        # Ensure device record exists
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Device).where(Device.id == device_id)
            )
            device = result.scalar_one_or_none()
            if not device:
                device = Device(id=device_id, name=f"Device-{device_id[:8]}")
                db.add(device)
            device.last_seen = datetime.utcnow()
            device.is_active = True
            await db.commit()

        logger.info("Device connected: %s (total: %d)",
                     device_id, len(self.active_connections))

    def disconnect(self, device_id: str) -> None:
        """Remove a disconnected device."""
        self.active_connections.pop(device_id, None)
        logger.info("Device disconnected: %s (remaining: %d)",
                     device_id, len(self.active_connections))

    async def send_to_device(self, device_id: str, message: str) -> bool:
        """Send a message to a specific device."""
        ws = self.active_connections.get(device_id)
        if ws:
            try:
                await ws.send_text(message)
                return True
            except Exception as e:
                logger.error("Send to %s failed: %s", device_id, e)
                self.disconnect(device_id)
        return False

    async def handle_message(self, device_id: str, raw_data: str) -> None:
        """
        Process incoming WebSocket message from a device.

        Expected format: JSON array of behavioral events.
        """
        try:
            events = json.loads(raw_data)
            if not isinstance(events, list):
                events = [events]
        except json.JSONDecodeError:
            logger.warning("Malformed JSON from %s: %s", device_id, raw_data[:200])
            return

        # Normalize event keys
        normalized = []
        for ev in events:
            normalized.append({
                "event_type": ev.get("type", ev.get("event_type", "UNKNOWN")),
                "package_name": ev.get("packageName", ev.get("package_name")),
                "timestamp": ev.get("timestamp", 0),
                "data": ev.get("data", "{}"),
            })

        # Buffer events in Redis
        for ev in normalized:
            await self.redis.buffer_event(device_id, ev)
            # Publish for live dashboard
            await self.redis.publish_event({
                "device_id": device_id,
                **ev,
            })

        # Check if enough events to analyze
        buffer_size = await self.redis.get_buffer_size(device_id)
        if buffer_size >= self.redis.BATCH_SIZE:
            await self._analyze_window(device_id)

    async def _analyze_window(self, device_id: str) -> None:
        """
        Flush the event buffer, extract features, run anomaly detection,
        update baseline, and create alerts if needed.
        """
        # Flush buffered events
        events = await self.redis.flush_buffer(device_id)
        if not events:
            return

        # Persist events to DB
        async with async_session() as db:
            for ev in events:
                db.add(BehaviorEvent(
                    device_id=device_id,
                    event_type=ev["event_type"],
                    package_name=ev.get("package_name"),
                    timestamp=ev.get("timestamp", 0),
                    data=json.dumps(ev.get("data")) if isinstance(ev.get("data"), dict) else ev.get("data"),
                ))
            await db.commit()

        # Extract 72-dim feature vector
        feature_vector = self.feature_extractor.extract(events)

        # Load device baseline
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Device).where(Device.id == device_id)
            )
            device = result.scalar_one_or_none()
            if not device:
                return

            baseline_mean = device.get_baseline_mean()
            baseline_cov = device.get_baseline_covariance()

            if baseline_mean is None or baseline_cov is None:
                # Still in accumulation phase — store sample and build baseline
                await self._accumulate_sample(device, feature_vector, db)
                return

            # Run anomaly detection
            detection = self.anomaly_detector.detect(
                feature_vector=feature_vector,
                baseline_mean=baseline_mean,
                baseline_cov=baseline_cov,
                distance_mean=device.distance_mean,
                distance_std=device.distance_std,
                cusum_pos=device.cusum_pos,
                cusum_neg=device.cusum_neg,
            )

            # Update CUSUM
            new_pos, new_neg, drift = self.baseline_manager.update_cusum(
                device.cusum_pos, device.cusum_neg,
                detection.mahalanobis_distance, device.distance_mean,
            )
            device.cusum_pos = new_pos
            device.cusum_neg = new_neg

            # Update distance statistics
            new_d_mean, new_d_std = self.baseline_manager.update_distance_stats(
                device.distance_mean, device.distance_std,
                detection.mahalanobis_distance, device.baseline_sample_count,
            )
            device.distance_mean = new_d_mean
            device.distance_std = new_d_std

            # Update baseline (only if safe)
            if not detection.is_anomaly or self.baseline_manager.should_update_after_anomaly(
                detection.threat_type.value, detection.severity
            ):
                new_mean, new_cov = self.baseline_manager.update_baseline(
                    baseline_mean, baseline_cov,
                    feature_vector, device.baseline_sample_count,
                )
                device.set_baseline_mean(new_mean)
                device.set_baseline_covariance(new_cov)

            device.baseline_sample_count += 1
            device.last_seen = datetime.utcnow()
            await db.commit()

            # Create alert if anomaly detected
            if detection.is_anomaly:
                alert = self.alert_manager.create_alert(
                    device_id=device_id,
                    severity=detection.severity,
                    threat_type=detection.threat_type.value,
                    message=detection.message,
                    confidence=detection.confidence,
                    mahalanobis_distance=detection.mahalanobis_distance,
                )
                async with async_session() as alert_db:
                    await self.alert_manager.save_alert(alert_db, alert)
                    await alert_db.commit()

                # Push alert to device via WebSocket
                alert_msg = self.alert_manager.alert_to_ws_message(alert)
                await self.send_to_device(device_id, alert_msg)

                # Publish to dashboard
                await self.redis.publish_alert(json.loads(alert_msg))

                logger.warning(
                    "ANOMALY: device=%s type=%s severity=%d confidence=%.2f",
                    device_id, detection.threat_type.value,
                    detection.severity, detection.confidence,
                )

    async def _accumulate_sample(
        self, device: Device, vector: np.ndarray, db
    ) -> None:
        """
        Store feature vectors during the baseline accumulation phase.
        Once enough samples are collected, initialize the baseline.
        """
        from config import settings

        # Store sample count (we keep vectors in a temporary structure)
        device.baseline_sample_count += 1
        count = device.baseline_sample_count

        # For simplicity, we build baseline from the first N samples
        # In production, you'd store vectors in a separate table
        current_mean = device.get_baseline_mean()

        if current_mean is None:
            # First sample
            device.set_baseline_mean(vector)
            device.set_baseline_covariance(
                np.eye(vector.shape[0]) * 0.01  # Initial identity cov
            )
        else:
            # Running mean update
            new_mean = current_mean + (vector - current_mean) / count
            device.set_baseline_mean(new_mean)

            # Running covariance (Welford's algorithm)
            diff = vector - current_mean
            new_diff = vector - new_mean
            cov = device.get_baseline_covariance()
            new_cov = cov + np.outer(diff, new_diff) / max(count, 2)
            device.set_baseline_covariance(new_cov)

        device.last_seen = datetime.utcnow()
        await db.commit()

        logger.info(
            "Baseline accumulation: device=%s samples=%d",
            device.id, count,
        )
