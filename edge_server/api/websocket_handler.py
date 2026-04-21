"""
WebSocket Connection Handler
==============================
Manages active WebSocket connections from Android devices,
parses incoming behavioral events, and routes them through
the analysis pipeline.
"""

import json
import logging
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from config import settings
from models.database import async_session
from models.device import Device
from models.behavior_event import BehaviorEvent
from services.feature_extractor import FeatureExtractor
from services.anomaly_detector import AnomalyDetector, AnomalyResult
from services.baseline_manager import BaselineManager
from services.alert_manager import AlertManager
from services.redis_buffer import RedisBuffer
from services.phishing_analyzer import PhishingAnalyzer
from services.xai_engine import explain_feature_contributions

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Tracks active WebSocket connections per device and manages
    the full analysis pipeline:
    event ingestion → buffering → feature extraction → anomaly detection → alerting
    """

    def __init__(self, redis_buffer: RedisBuffer):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.redis = redis_buffer
        self.feature_extractor = FeatureExtractor()
        self.anomaly_detector = AnomalyDetector()
        self.baseline_manager = BaselineManager()
        self.alert_manager = AlertManager()
        self.phishing_analyzer = PhishingAnalyzer(
            alert_threshold=settings.phishing_alert_threshold,
            suspicious_threshold=settings.phishing_suspicious_threshold,
            safe_browsing_api_key=settings.safe_browsing_api_key,
        )
        # Deduplicate immediate indicator alerts (e.g., same malicious app/domain repeated).
        self._indicator_alert_cache: Dict[str, float] = {}

    def _socket_count(self) -> int:
        return sum(len(sockets) for sockets in self.active_connections.values())

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        """Accept a new device connection."""
        await websocket.accept()
        device_sockets = self.active_connections.setdefault(device_id, [])
        device_sockets.append(websocket)

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

        logger.info(
            "Device connected: %s (devices=%d sockets=%d)",
            device_id,
            len(self.active_connections),
            self._socket_count(),
        )

    def disconnect(self, device_id: str, websocket: Optional[WebSocket] = None) -> None:
        """Remove a disconnected socket (or all sockets for a device)."""
        device_sockets = self.active_connections.get(device_id)
        if not device_sockets:
            return

        if websocket is None:
            self.active_connections.pop(device_id, None)
        else:
            try:
                device_sockets.remove(websocket)
            except ValueError:
                pass

            if not device_sockets:
                self.active_connections.pop(device_id, None)

        logger.info(
            "Device disconnected: %s (devices=%d sockets=%d)",
            device_id,
            len(self.active_connections),
            self._socket_count(),
        )

    async def send_to_device(self, device_id: str, message: str) -> bool:
        """Send a message to a specific device."""
        sockets = list(self.active_connections.get(device_id, []))
        delivered = False

        for ws in sockets:
            try:
                await ws.send_text(message)
                delivered = True
            except Exception as e:
                logger.error("Send to %s failed: %s", device_id, e)
                self.disconnect(device_id, ws)

        return delivered

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

        device_id = str(device_id or "").strip()
        if not device_id:
            logger.warning("Dropping message with empty device id")
            return

        if self._is_ignored_device(device_id):
            logger.info("Ignoring message from configured non-production device: %s", device_id)
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

        # Immediate rule check so known malicious indicators alert quickly.
        immediate_rule_alert = self._evaluate_rule_alert(normalized)
        if (
            immediate_rule_alert
            and immediate_rule_alert.get("indicator")
            and self._should_emit_indicator_alert(device_id, immediate_rule_alert)
        ):
            await self._emit_rule_alert(device_id, immediate_rule_alert, normalized, source="rule-immediate")

        # ── Fast-path: Canary file access ──
        await self._check_canary_fast_path(device_id, normalized)

        # ── Fast-path: Phishing URL detection ──
        await self._check_phishing_fast_path(device_id, normalized)

        # ── Fast-path: Permission access alerts (side-loaded apps) ──
        await self._check_permission_fast_path(device_id, normalized)

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
        if self._is_ignored_device(device_id):
            await self.redis.flush_buffer(device_id)
            logger.info("Skipped analysis for ignored device: %s", device_id)
            return

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
            rule_alert = self._evaluate_rule_alert(events)

            # If this is a repeated indicator-only rule alert, suppress duplicates.
            if rule_alert and not detection.is_anomaly:
                if not self._should_emit_indicator_alert(device_id, rule_alert):
                    rule_alert = None

            is_suspicious_window = detection.is_anomaly or rule_alert is not None

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
            active_threat_type = (
                detection.threat_type.value
                if detection.is_anomaly
                else (rule_alert["threat_type"] if rule_alert else "NONE")
            )
            active_severity = (
                detection.severity
                if detection.is_anomaly
                else (rule_alert["severity"] if rule_alert else 0)
            )

            if (not is_suspicious_window) or self.baseline_manager.should_update_after_anomaly(
                active_threat_type, active_severity
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

            # Create alert if model anomaly or rule trigger is present
            if is_suspicious_window:
                alert_severity = detection.severity
                alert_threat_type = detection.threat_type.value
                alert_message = detection.message
                alert_confidence = detection.confidence
                alert_distance = detection.mahalanobis_distance
                alert_source = "model"
                action_targets = self._extract_action_targets(events)

                if not detection.is_anomaly and rule_alert:
                    alert_severity = int(rule_alert["severity"])
                    alert_threat_type = str(rule_alert["threat_type"])
                    alert_message = str(rule_alert["message"])
                    alert_confidence = float(rule_alert["confidence"])
                    alert_distance = 0.0
                    alert_source = "rule"
                elif detection.is_anomaly and rule_alert:
                    if int(rule_alert["severity"]) > alert_severity:
                        alert_severity = int(rule_alert["severity"])
                        alert_threat_type = str(rule_alert["threat_type"])
                        alert_message = str(rule_alert["message"])
                        alert_confidence = max(alert_confidence, float(rule_alert["confidence"]))
                    else:
                        alert_message = f"{alert_message} | {rule_alert['message']}"
                        alert_confidence = max(alert_confidence, float(rule_alert["confidence"]))
                    alert_source = "model+rule"

                xai_explanation = self._build_xai_explanation(
                    events=events,
                    detection=detection,
                    rule_alert=rule_alert,
                    alert_source=alert_source,
                    selected_threat_type=alert_threat_type,
                    selected_severity=alert_severity,
                    selected_message=alert_message,
                    selected_confidence=alert_confidence,
                    selected_distance=alert_distance,
                    selected_threshold=detection.threshold,
                )

                alert = self.alert_manager.create_alert(
                    device_id=device_id,
                    severity=alert_severity,
                    threat_type=alert_threat_type,
                    message=alert_message,
                    confidence=alert_confidence,
                    mahalanobis_distance=alert_distance,
                    target_package=action_targets.get("target_package"),
                    target_uid=action_targets.get("target_uid"),
                    xai_explanation=xai_explanation,
                )
                async with async_session() as alert_db:
                    await self.alert_manager.save_alert(alert_db, alert)
                    await alert_db.commit()

                # Push alert to device via WebSocket
                alert_msg = self.alert_manager.alert_to_ws_message(alert)
                delivered = await self.send_to_device(device_id, alert_msg)
                if not delivered:
                    logger.warning("Alert %s could not be delivered to any active socket", alert.anomaly_id)

                # Publish to dashboard
                await self.redis.publish_alert(json.loads(alert_msg))

                logger.warning(
                    "ALERT: device=%s source=%s type=%s severity=%d confidence=%.2f",
                    device_id, alert_source, alert_threat_type,
                    alert_severity, alert_confidence,
                )

    def _should_emit_indicator_alert(self, device_id: str, rule_alert: Dict[str, Any]) -> bool:
        """
        Apply cooldown only for indicator-based rules (e.g., app/domain IOC).

        Non-indicator rule alerts are not throttled by this helper.
        """
        indicator = str(rule_alert.get("indicator", "")).strip()
        if not indicator:
            return True

        cache_key = f"{device_id}:{indicator.lower()}"
        now_ts = datetime.utcnow().timestamp()
        cooldown = max(0, int(settings.rule_alert_cooldown_seconds))

        last_ts = self._indicator_alert_cache.get(cache_key)
        if last_ts is not None and (now_ts - last_ts) < cooldown:
            return False

        self._indicator_alert_cache[cache_key] = now_ts

        # Prune stale cache entries opportunistically.
        stale_cutoff = now_ts - max(cooldown * 3, 300)
        stale_keys = [key for key, ts in self._indicator_alert_cache.items() if ts < stale_cutoff]
        for key in stale_keys:
            self._indicator_alert_cache.pop(key, None)

        return True

    async def _emit_rule_alert(
        self,
        device_id: str,
        rule_alert: Dict[str, Any],
        events: List[Dict[str, Any]],
        source: str,
    ) -> None:
        """Create, persist, and deliver a rule-based alert."""
        action_targets = self._extract_action_targets(events)
        explicit_target_package = rule_alert.get("target_package")
        if isinstance(explicit_target_package, str) and explicit_target_package.strip():
            action_targets["target_package"] = explicit_target_package.strip()

        alert = self.alert_manager.create_alert(
            device_id=device_id,
            severity=int(rule_alert["severity"]),
            threat_type=str(rule_alert["threat_type"]),
            message=str(rule_alert["message"]),
            confidence=float(rule_alert["confidence"]),
            mahalanobis_distance=0.0,
            target_package=action_targets.get("target_package"),
            target_uid=action_targets.get("target_uid"),
            xai_explanation=self._build_xai_explanation(
                events=events,
                detection=None,
                rule_alert=rule_alert,
                alert_source=source,
                selected_threat_type=str(rule_alert["threat_type"]),
                selected_severity=int(rule_alert["severity"]),
                selected_message=str(rule_alert["message"]),
                selected_confidence=float(rule_alert["confidence"]),
                selected_distance=0.0,
                selected_threshold=None,
            ),
        )

        async with async_session() as alert_db:
            await self.alert_manager.save_alert(alert_db, alert)
            await alert_db.commit()

        alert_msg = self.alert_manager.alert_to_ws_message(alert)
        delivered = await self.send_to_device(device_id, alert_msg)
        if not delivered:
            logger.warning("Alert %s could not be delivered to any active socket", alert.anomaly_id)

        await self.redis.publish_alert(json.loads(alert_msg))

        logger.warning(
            "ALERT: device=%s source=%s type=%s severity=%d confidence=%.2f",
            device_id,
            source,
            str(rule_alert["threat_type"]),
            int(rule_alert["severity"]),
            float(rule_alert["confidence"]),
        )

    async def _check_phishing_fast_path(
        self,
        device_id: str,
        events: List[Dict[str, Any]],
    ) -> None:
        """
        Fast-path phishing detection for WEB_DOMAIN events.

        Runs the PhishingAnalyzer on any incoming web domain event and
        emits an immediate alert if the risk score exceeds the threshold.
        """
        for ev in events:
            if str(ev.get("event_type", "")).upper() != "WEB_DOMAIN":
                continue

            data = self._parse_event_data(ev)
            domain = str(data.get("domain", "")).strip().lower()
            url = data.get("url")

            if not domain:
                continue

            result = self.phishing_analyzer.analyze(domain, url)

            if result.classification == "safe":
                continue

            # Build indicator key for cooldown dedup
            indicator_key = f"phishing:{domain}"
            phishing_alert = {
                "severity": 9 if result.classification == "phishing" else 6,
                "threat_type": "PHISHING",
                "message": (
                    f"{'⚠ Phishing' if result.classification == 'phishing' else 'Suspicious'} "
                    f"website detected: {domain}"
                    + (f" (impersonating {result.matched_brand})" if result.matched_brand else "")
                    + f" — risk score {result.risk_score:.0%}"
                ),
                "confidence": result.risk_score,
                "indicator": indicator_key,
                "target_package": ev.get("package_name"),
            }

            if not self._should_emit_indicator_alert(device_id, phishing_alert):
                continue

            logger.warning(
                "PHISHING detected: device=%s domain=%s score=%.2f brand=%s reasons=%s",
                device_id, domain, result.risk_score,
                result.matched_brand, result.reasons,
            )
            await self._emit_rule_alert(
                device_id, phishing_alert, events, source="phishing-analyzer",
            )

    async def _check_permission_fast_path(
        self,
        device_id: str,
        events: List[Dict[str, Any]],
    ) -> None:
        """
        Fast-path permission access detection.

        Side-loaded apps accessing camera/mic/location trigger immediate
        alerts without waiting for the analysis window.
        """
        for ev in events:
            if str(ev.get("event_type", "")).upper() != "PERMISSION_ACCESS":
                continue

            data = self._parse_event_data(ev)
            permission = str(data.get("permission", "")).upper()
            is_side_loaded = bool(data.get("isSideLoaded", False))
            pkg = str(data.get("packageName", ev.get("package_name", "unknown")))

            # Only fast-path for side-loaded apps accessing sensitive permissions
            if not is_side_loaded:
                continue
            if permission not in ("CAMERA", "RECORD_AUDIO", "FINE_LOCATION", "COARSE_LOCATION"):
                continue

            if permission in ("CAMERA", "RECORD_AUDIO"):
                severity = 8
                threat_type = "INSIDER_THREAT"
                perm_label = permission.lower().replace("_", " ")
                message = (
                    f"⚠ Side-loaded app '{pkg}' accessed {perm_label} — "
                    f"potential surveillance risk"
                )
            else:
                severity = 7
                threat_type = "DEVICE_MISUSE"
                message = f"Side-loaded app '{pkg}' accessed location data"

            perm_alert = {
                "severity": severity,
                "threat_type": threat_type,
                "message": message,
                "confidence": 0.90,
                "indicator": f"perm:{pkg}:{permission}",
                "target_package": pkg,
            }

            if not self._should_emit_indicator_alert(device_id, perm_alert):
                continue

            logger.warning(
                "PERMISSION alert: device=%s pkg=%s perm=%s sideLoaded=%s",
                device_id, pkg, permission, is_side_loaded,
            )
            await self._emit_rule_alert(
                device_id, perm_alert, events, source="permission-monitor",
            )

    async def _check_canary_fast_path(
        self,
        device_id: str,
        events: List[Dict[str, Any]],
    ) -> None:
        """
        Fast-path canary file access detection.

        Any interaction with a honey file triggers a critical Severity 10 alert.
        """
        for ev in events:
            if str(ev.get("event_type", "")).upper() != "CANARY_FILE_ACCESS":
                continue

            data = self._parse_event_data(ev)
            file_name = str(data.get("fileName", "unknown"))
            action = str(data.get("action", "ACCESS"))

            canary_alert = {
                "severity": 10,
                "threat_type": "MALWARE_MIMICRY",
                "message": f"CRITICAL: Unauthorized {action} of decoy document '{file_name}' detected. Possible Ransomware/Spyware.",
                "confidence": 0.99,
                "indicator": f"canary:{file_name}",
            }

            if not self._should_emit_indicator_alert(device_id, canary_alert):
                continue

            logger.critical(
                "CANARY TRIGGERED: device=%s file=%s action=%s",
                device_id, file_name, action,
            )
            await self._emit_rule_alert(
                device_id, canary_alert, events, source="canary-manager",
            )

    @staticmethod
    def _window_span_seconds(events: List[Dict[str, Any]]) -> Optional[float]:
        """Return event window timespan in seconds when timestamps are present."""
        timestamps: List[float] = []
        for ev in events:
            raw = ev.get("timestamp")
            try:
                ts = float(raw)
            except (TypeError, ValueError):
                continue
            if ts <= 0:
                continue
            # Android payloads are usually epoch milliseconds.
            if ts > 10_000_000_000:
                ts /= 1000.0
            timestamps.append(ts)

        if len(timestamps) < 2:
            return None

        span = max(timestamps) - min(timestamps)
        return round(max(span, 0.0), 3)

    @staticmethod
    def _top_event_types(events: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
        """Return top event types in the current analysis window."""
        counts: Counter[str] = Counter(
            str(ev.get("event_type", "UNKNOWN")).upper() for ev in events
        )
        return [
            {"event_type": event_type, "count": count}
            for event_type, count in counts.most_common(max(limit, 1))
        ]

    @staticmethod
    def _dominant_package(events: List[Dict[str, Any]]) -> Optional[str]:
        """Return the most frequently observed package in the current window."""
        package_counts: Counter[str] = Counter()

        for ev in events:
            data = ConnectionManager._parse_event_data(ev)
            package_candidates = [
                ev.get("package_name"),
                data.get("package"),
                data.get("packageName"),
                data.get("targetPackage"),
                data.get("processName"),
            ]

            for candidate in package_candidates:
                if not isinstance(candidate, str):
                    continue
                package_name = candidate.strip().lower()
                if not package_name or ConnectionManager._is_ignored_package(package_name):
                    continue
                package_counts[package_name] += 1

        if not package_counts:
            return None
        return package_counts.most_common(1)[0][0]

    @staticmethod
    def _build_xai_explanation(
        events: List[Dict[str, Any]],
        detection: Optional[AnomalyResult],
        rule_alert: Optional[Dict[str, Any]],
        alert_source: str,
        selected_threat_type: str,
        selected_severity: int,
        selected_message: str,
        selected_confidence: float,
        selected_distance: float,
        selected_threshold: Optional[float],
    ) -> Dict[str, Any]:
        """Build a concise, structured explanation payload for each alert."""
        event_count = len(events)
        span_seconds = ConnectionManager._window_span_seconds(events)
        top_event_types = ConnectionManager._top_event_types(events, limit=3)
        dominant_package = ConnectionManager._dominant_package(events)
        indicator = str(rule_alert.get("indicator", "")).strip() if rule_alert else ""

        threshold_value = (
            float(selected_threshold)
            if selected_threshold is not None
            else (float(detection.threshold) if detection is not None else 0.0)
        )
        has_model_context = detection is not None and threshold_value > 0
        distance_ratio = (
            round(float(selected_distance) / threshold_value, 3)
            if has_model_context
            else None
        )

        if has_model_context and distance_ratio is not None:
            summary = (
                f"{selected_threat_type} risk: {event_count} events in this window; "
                f"distance {selected_distance:.2f} vs threshold {threshold_value:.2f} "
                f"({distance_ratio:.2f}x), confidence {selected_confidence:.2f}."
            )
        elif indicator:
            summary = (
                f"{selected_threat_type} risk: matched indicator {indicator} "
                f"across {event_count} recent events (confidence {selected_confidence:.2f})."
            )
        else:
            summary = (
                f"{selected_threat_type} risk: {event_count} recent events triggered "
                f"security rules (confidence {selected_confidence:.2f})."
            )

        factors: List[str] = []
        if has_model_context and distance_ratio is not None:
            factors.append(
                f"Model anomaly score crossed threshold ({selected_distance:.2f} > {threshold_value:.2f})."
            )
            # Add detailed Mahalanobis feature contributions using XAI engine
            if hasattr(detection, "feature_contributions") and detection.feature_contributions:
                feature_explanations = explain_feature_contributions(detection.feature_contributions)
                factors.extend(feature_explanations)
                
        if indicator:
            factors.append(f"Matched configured threat indicator: {indicator}.")
        if dominant_package:
            factors.append(f"Dominant package in window: {dominant_package}.")
        if top_event_types:
            compact_types = ", ".join(
                f"{item['event_type']} x{item['count']}" for item in top_event_types
            )
            factors.append(f"Top activity types: {compact_types}.")
        if span_seconds is not None:
            factors.append(f"Behavioral window span: {span_seconds:.2f}s.")

        return {
            "version": "xai-v1",
            "summary": summary,
            "source": alert_source,
            "threat_type": selected_threat_type,
            "severity": int(selected_severity),
            "confidence": round(float(selected_confidence), 3),
            "message": str(selected_message),
            "factors": factors[:5],
            "window": {
                "event_count": event_count,
                "span_seconds": span_seconds,
                "top_event_types": top_event_types,
                "dominant_package": dominant_package,
            },
            "model": {
                "distance": round(float(selected_distance), 4),
                "threshold": round(float(threshold_value), 4) if has_model_context else None,
                "distance_ratio": distance_ratio,
            },
            "rule": {
                "indicator": indicator or None,
                "rule_message": str(rule_alert.get("message", "")) if rule_alert else None,
            },
        }

    @staticmethod
    def _parse_event_data(event: Dict[str, Any]) -> Dict[str, Any]:
        """Parse event payload into a dictionary."""
        data = event.get("data", {})
        if isinstance(data, dict):
            return data
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """Safely convert arbitrary values to float."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _extract_action_targets(events: list) -> Dict[str, Optional[Any]]:
        """Infer likely action targets from event content in the current window."""
        package_counts: Dict[str, int] = {}
        uid_scores: Dict[int, float] = {}

        for ev in events:
            data = ConnectionManager._parse_event_data(ev)
            event_type = str(ev.get("event_type", "")).upper()

            package_candidates = [
                ev.get("package_name"),
                data.get("package"),
                data.get("packageName"),
                data.get("targetPackage"),
                data.get("processName"),
            ]
            for candidate in package_candidates:
                if not isinstance(candidate, str):
                    continue
                package_name = candidate.strip()
                if not package_name:
                    continue
                normalized_package = package_name.lower()
                if ConnectionManager._is_ignored_package(normalized_package):
                    continue
                package_counts[normalized_package] = package_counts.get(normalized_package, 0) + 1

            if event_type == "NETWORK_APP":
                uid_value = data.get("uid")
                try:
                    uid = int(uid_value)
                except (TypeError, ValueError):
                    uid = None

                if uid is not None and uid >= 0:
                    rx = ConnectionManager._safe_float(data.get("rxBytesDelta"), default=0.0)
                    tx = ConnectionManager._safe_float(data.get("txBytesDelta"), default=0.0)
                    score = max(0.0, rx) + max(0.0, tx)
                    uid_scores[uid] = uid_scores.get(uid, 0.0) + (score if score > 0 else 1.0)

        target_package = None
        if package_counts:
            target_package = max(package_counts.items(), key=lambda kv: kv[1])[0]

        target_uid = None
        if uid_scores:
            target_uid = max(uid_scores.items(), key=lambda kv: kv[1])[0]

        return {
            "target_package": target_package,
            "target_uid": target_uid,
        }

    @staticmethod
    def _evaluate_rule_alert(events: list) -> Optional[Dict[str, Any]]:
        """
        Rule-based alerting for security/system/network conditions.

        Returns an alert payload or None when no rule matches.
        """
        package_events = 0
        auth_events = 0
        low_memory_events = 0
        battery_critical_events = 0
        network_flow_events = 0
        total_network_bytes = 0.0
        observed_packages: set[str] = set()
        observed_domains: set[str] = set()

        malicious_apps = ConnectionManager._parse_csv_setting(settings.malicious_apps)
        malicious_domains = ConnectionManager._parse_csv_setting(settings.malicious_domains)
        ignored_packages = ConnectionManager._parse_csv_setting(settings.ignored_alert_packages)

        for ev in events:
            etype = str(ev.get("event_type", "")).upper()
            data = ConnectionManager._parse_event_data(ev)

            package_candidates = [
                ev.get("package_name"),
                data.get("package"),
                data.get("packageName"),
                data.get("targetPackage"),
            ]
            normalized_packages: list[str] = []
            for candidate in package_candidates:
                if isinstance(candidate, str) and candidate.strip():
                    normalized_packages.append(candidate.strip().lower())

            if normalized_packages and all(
                ConnectionManager._is_ignored_package(pkg, ignored_packages)
                for pkg in normalized_packages
            ):
                continue

            for package_name in normalized_packages:
                if not ConnectionManager._is_ignored_package(package_name, ignored_packages):
                    observed_packages.add(package_name)

            domain_candidates = [
                data.get("domain"),
                data.get("host"),
                data.get("url"),
                data.get("dstHost"),
            ]
            for candidate in domain_candidates:
                normalized_domain = ConnectionManager._normalize_domain(candidate)
                if normalized_domain:
                    observed_domains.add(normalized_domain)

            if etype == "SECURITY_PACKAGE_EVENT":
                package_events += 1
            elif etype == "SECURITY_AUTH_EVENT":
                auth_events += 1
            elif etype == "SYSTEM_STATE":
                if bool(data.get("lowMemory", False)):
                    low_memory_events += 1
                battery_pct = ConnectionManager._safe_float(data.get("batteryPct"), default=-1.0)
                if 0 <= battery_pct <= 10:
                    battery_critical_events += 1

            if etype in ("NETWORK_TRAFFIC", "NETWORK_APP"):
                rx = ConnectionManager._safe_float(data.get("rxBytesDelta"), default=0.0)
                tx = ConnectionManager._safe_float(data.get("txBytesDelta"), default=0.0)
                total_network_bytes += max(0.0, rx) + max(0.0, tx)
                network_flow_events += 1
            elif etype == "NETWORK_FLOW":
                total_network_bytes += max(0.0, ConnectionManager._safe_float(data.get("bytes"), default=0.0))
                network_flow_events += 1

        total_network_mb = total_network_bytes / (1024.0 * 1024.0)

        # Keep highest severity rule when multiple rules match.
        rule_alert: Optional[Dict[str, Any]] = None

        for package_name in sorted(observed_packages):
            if package_name in malicious_apps:
                candidate = {
                    "severity": 9,
                    "threat_type": "MALWARE_MIMICRY",
                    "message": f"Known malicious app activity detected: {package_name}",
                    "confidence": 0.97,
                    "indicator": f"app:{package_name}",
                    "target_package": package_name,
                }
                if rule_alert is None or candidate["severity"] >= rule_alert["severity"]:
                    rule_alert = candidate

        for domain in sorted(observed_domains):
            if ConnectionManager._is_malicious_domain(domain, malicious_domains):
                candidate = {
                    "severity": 8,
                    "threat_type": "MALWARE_MIMICRY",
                    "message": f"Known malicious website detected: {domain}",
                    "confidence": 0.94,
                    "indicator": f"domain:{domain}",
                }
                if rule_alert is None or candidate["severity"] >= rule_alert["severity"]:
                    rule_alert = candidate

        if package_events >= 2:
            severity = min(9, 6 + package_events)
            candidate = {
                "severity": severity,
                "threat_type": "INSIDER_THREAT",
                "message": f"{package_events} app package modifications detected in one analysis window",
                "confidence": min(0.7 + package_events * 0.05, 0.95),
            }
            if rule_alert is None or candidate["severity"] >= rule_alert["severity"]:
                rule_alert = candidate

        if auth_events >= 15:
            candidate = {
                "severity": 7,
                "threat_type": "INSIDER_THREAT",
                "message": f"Unusual authentication/screen churn detected ({auth_events} events)",
                "confidence": 0.8,
            }
            if rule_alert is None or candidate["severity"] >= rule_alert["severity"]:
                rule_alert = candidate

        if total_network_mb >= 25.0 and (low_memory_events > 0 or battery_critical_events > 0):
            candidate = {
                "severity": 8,
                "threat_type": "DEVICE_MISUSE",
                "message": (
                    f"High network burst ({total_network_mb:.1f} MB) during system stress "
                    f"(low_memory={low_memory_events}, battery_critical={battery_critical_events})"
                ),
                "confidence": 0.85,
            }
            if rule_alert is None or candidate["severity"] >= rule_alert["severity"]:
                rule_alert = candidate

        if network_flow_events >= 30 and total_network_mb >= 10.0:
            candidate = {
                "severity": 7,
                "threat_type": "DEVICE_MISUSE",
                "message": f"Dense network flow burst detected ({network_flow_events} flow events)",
                "confidence": 0.8,
            }
            if rule_alert is None or candidate["severity"] >= rule_alert["severity"]:
                rule_alert = candidate

        # ── Permission Access Rules ──
        permission_events = [
            ev for ev in events
            if str(ev.get("event_type", "")).upper() == "PERMISSION_ACCESS"
        ]
        for ev in permission_events:
            data = ConnectionManager._parse_event_data(ev)
            permission = str(data.get("permission", "")).upper()
            is_side_loaded = bool(data.get("isSideLoaded", False))
            pkg = str(data.get("packageName", ev.get("package_name", "unknown")))

            if is_side_loaded and permission in ("CAMERA", "RECORD_AUDIO"):
                candidate = {
                    "severity": 8,
                    "threat_type": "INSIDER_THREAT",
                    "message": (
                        f"Side-loaded app '{pkg}' accessed {permission.lower().replace('_', ' ')} — "
                        f"potential surveillance risk"
                    ),
                    "confidence": 0.90,
                    "indicator": f"perm:{pkg}:{permission}",
                    "target_package": pkg,
                }
                if rule_alert is None or candidate["severity"] >= rule_alert["severity"]:
                    rule_alert = candidate

            elif is_side_loaded and permission in ("FINE_LOCATION", "COARSE_LOCATION"):
                candidate = {
                    "severity": 7,
                    "threat_type": "DEVICE_MISUSE",
                    "message": (
                        f"Side-loaded app '{pkg}' accessed location data"
                    ),
                    "confidence": 0.85,
                    "indicator": f"perm:{pkg}:{permission}",
                    "target_package": pkg,
                }
                if rule_alert is None or candidate["severity"] >= rule_alert["severity"]:
                    rule_alert = candidate

            elif not is_side_loaded and permission in ("CAMERA", "RECORD_AUDIO"):
                candidate = {
                    "severity": 5,
                    "threat_type": "DEVICE_MISUSE",
                    "message": (
                        f"Third-party app '{pkg}' accessed {permission.lower().replace('_', ' ')}"
                    ),
                    "confidence": 0.65,
                }
                if rule_alert is None or candidate["severity"] >= rule_alert["severity"]:
                    rule_alert = candidate

        return rule_alert

    @staticmethod
    def _parse_csv_setting(raw_value: str) -> set[str]:
        """Parse comma-separated settings into lowercase tokens."""
        return {
            token.strip().lower()
            for token in str(raw_value or "").split(",")
            if token.strip()
        }

    @staticmethod
    def _is_ignored_device(device_id: str) -> bool:
        """Check whether alerts/events for this device should be ignored."""
        normalized = str(device_id or "").strip().lower()
        if not normalized:
            return False

        ignored_ids = ConnectionManager._parse_csv_setting(settings.ignored_alert_device_ids)
        if normalized in ignored_ids:
            return True

        ignored_prefixes = ConnectionManager._parse_csv_setting(settings.ignored_alert_device_prefixes)
        return any(normalized.startswith(prefix) for prefix in ignored_prefixes)

    @staticmethod
    def _is_ignored_package(package_name: str, ignored_packages: Optional[set[str]] = None) -> bool:
        """Check whether package-sourced signals should be ignored."""
        normalized = str(package_name or "").strip().lower()
        if not normalized:
            return False

        blocked = (
            ignored_packages
            if ignored_packages is not None
            else ConnectionManager._parse_csv_setting(settings.ignored_alert_packages)
        )
        return normalized in blocked

    @staticmethod
    def _normalize_domain(value: Any) -> Optional[str]:
        """Normalize a host/domain/url-ish value to a bare lowercase domain."""
        if not isinstance(value, str):
            return None

        candidate = value.strip().lower()
        if not candidate:
            return None

        if "://" in candidate:
            parsed = urlparse(candidate)
            host = parsed.hostname or ""
        else:
            host = candidate.split("/")[0]

        host = host.strip().strip(".")
        if host.startswith("www."):
            host = host[4:]

        if ":" in host:
            host = host.split(":", 1)[0]

        if not host:
            return None

        # Keep domains only (ignore plain IPv4 for domain IOC matching).
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
            return None

        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", host):
            return None

        return host

    @staticmethod
    def _is_malicious_domain(domain: str, blocked_domains: set[str]) -> bool:
        """Match exact blocked domain or any subdomain of a blocked domain."""
        normalized = ConnectionManager._normalize_domain(domain)
        if not normalized:
            return False

        for blocked in blocked_domains:
            if normalized == blocked or normalized.endswith(f".{blocked}"):
                return True
        return False

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
