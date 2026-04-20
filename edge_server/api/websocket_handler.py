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
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.redis = redis_buffer
        self.feature_extractor = FeatureExtractor()
        self.anomaly_detector = AnomalyDetector()
        self.baseline_manager = BaselineManager()
        self.alert_manager = AlertManager()
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

                alert = self.alert_manager.create_alert(
                    device_id=device_id,
                    severity=alert_severity,
                    threat_type=alert_threat_type,
                    message=alert_message,
                    confidence=alert_confidence,
                    mahalanobis_distance=alert_distance,
                    target_package=action_targets.get("target_package"),
                    target_uid=action_targets.get("target_uid"),
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
