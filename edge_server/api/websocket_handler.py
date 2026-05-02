"""
WebSocket Connection Handler
==============================
Manages active WebSocket connections from Android devices,
parses incoming behavioral events, and routes them through
the analysis pipeline.
"""

import asyncio
import json
import logging
import re
from collections import Counter
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from config import settings
from models.database import async_session
from models.device import Device
from models.behavior_event import BehaviorEvent
from services.feature_extractor import FeatureExtractor
from services.anomaly_detector import AnomalyDetector, AnomalyResult, ThreatType
from services.baseline_manager import BaselineManager
from services.alert_manager import AlertManager
from services.ml_inference_loader import EnsembleInferenceLoader
from services.redis_buffer import RedisBuffer
from services.phishing_analyzer import PhishingAnalyzer
from services.xai_engine import explain_feature_contributions, record_anomaly_contributions
from services.crypto_manager import crypto_manager
from services.action_executor import ActionExecutor   # ✅ moved import to top

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
        self.ml_inference = EnsembleInferenceLoader()
        self.baseline_manager = BaselineManager()
        self.alert_manager = AlertManager()
        self.phishing_analyzer = PhishingAnalyzer(
            alert_threshold=settings.phishing_alert_threshold,
            suspicious_threshold=settings.phishing_suspicious_threshold,
            safe_browsing_api_key=settings.safe_browsing_api_key,
        )
        # Deduplicate immediate indicator alerts (e.g., same malicious app/domain repeated).
        self._indicator_alert_cache: Dict[str, float] = {}
        self._cache_lock = asyncio.Lock()

        # Rate Limiting state
        self._message_counts: Dict[str, int] = {}
        self._last_rate_reset: Dict[str, datetime] = {}
        
    async def _to_thread(self, func, *args):
        """Fallback for asyncio.to_thread (available in Python 3.9+)."""
        if hasattr(asyncio, "to_thread"):
            return await asyncio.to_thread(func, *args)
        loop = asyncio.get_running_loop()
        import functools
        return await loop.run_in_executor(None, functools.partial(func, *args))

    def _socket_count(self) -> int:
        return sum(len(sockets) for sockets in self.active_connections.values())

    def _validate_device_token(self, device_id: str, token: Optional[str]) -> bool:
        """Validate device authentication token using HMAC."""
        if not token:
            return getattr(settings, 'environment', "production") == "development"

        expected_token = getattr(settings, 'device_shared_secret', None)
        if expected_token:
            expected_hmac = hmac.new(
                expected_token.encode(),
                device_id.encode(),
                hashlib.sha256
            ).hexdigest()
            if hmac.compare_digest(token, expected_hmac):
                return True
            return hmac.compare_digest(token, expected_token)

        return hmac.compare_digest(token, device_id)

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        """Accept a new device connection with authentication."""
        token = websocket.query_params.get("token")
        if not token:
            token = websocket.headers.get("authorization")
            if token and token.startswith("Bearer "):
                token = token[7:]

        if not self._validate_device_token(device_id, token):
            await websocket.close(code=4001, reason="Invalid or missing authentication token")
            return

        await websocket.accept()
        device_sockets = self.active_connections.setdefault(device_id, [])
        device_sockets.append(websocket)

        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(select(Device).where(Device.id == device_id))
            device = result.scalar_one_or_none()
            if not device:
                device = Device(id=device_id, name=f"Device-{device_id[:8]}")
                db.add(device)
            device.last_seen = datetime.utcnow()
            device.is_active = True
            await db.commit()

        logger.info(
            "Device connected: %s (devices=%d sockets=%d)",
            device_id, len(self.active_connections), self._socket_count(),
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
            device_id, len(self.active_connections), self._socket_count(),
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
        """Process incoming WebSocket message from a device."""
        try:
            events = json.loads(raw_data)
            if not isinstance(events, list):
                events = [events]
        except json.JSONDecodeError:
            logger.warning("Malformed JSON from %s: %s", device_id, raw_data[:200])
            return

        # Rate limiting
        now = datetime.utcnow()
        last_reset = self._last_rate_reset.get(device_id, now)
        if (now - last_reset).total_seconds() >= 1.0:
            self._message_counts[device_id] = 0
            self._last_rate_reset[device_id] = now

        self._message_counts[device_id] = self._message_counts.get(device_id, 0) + 1
        if self._message_counts[device_id] > settings.max_ws_rate_per_sec:
            if self._message_counts[device_id] == settings.max_ws_rate_per_sec + 1:
                logger.warning("Rate limit exceeded for device %s", device_id)
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

        # Filter out ignored packages (Flaw #26 cleanup)
        ignored_pkgs = {p.strip() for p in settings.ignored_alert_packages.split(",") if p.strip()}
        normalized = [ev for ev in normalized if ev.get("package_name") not in ignored_pkgs]

        if not normalized:
            return

        # Immediate rule check
        immediate_rule_alert = self._evaluate_rule_alert(normalized)
        if immediate_rule_alert and immediate_rule_alert.get("indicator") and await self._should_emit_indicator_alert(device_id, immediate_rule_alert):
            await self._emit_rule_alert(device_id, immediate_rule_alert, normalized, source="rule-immediate")

        # Fast‑path checks
        await self._check_canary_fast_path(device_id, normalized)
        await self._check_phishing_fast_path(device_id, normalized)
        await self._check_permission_fast_path(device_id, normalized)

        # Buffer events
        for ev in normalized:
            await self.redis.buffer_event(device_id, ev)
            await self.redis.publish_event({"device_id": device_id, **ev})

        buffer_size = await self.redis.get_buffer_size(device_id)
        if buffer_size >= self.redis.BATCH_SIZE:
            await self._analyze_window(device_id)

    async def _analyze_window(self, device_id: str) -> None:
        """Flush event buffer, extract features, run anomaly detection, update baseline, and create alerts."""
        if self._is_ignored_device(device_id):
            await self.redis.flush_buffer(device_id)
            logger.info("Skipped analysis for ignored device: %s", device_id)
            return

        events = await self.redis.flush_buffer(device_id)
        if not events:
            return

        # Time zone shift detection
        tz_offset = None
        for ev in events:
            if ev.get("event_type") == "SYSTEM_STATE":
                data = ev.get("data", {})
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except:
                        data = {}
                if isinstance(data, dict) and "tz_offset" in data:
                    tz_offset = data["tz_offset"]
                    break

        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(select(Device).where(Device.id == device_id))
            device = result.scalar_one_or_none()
            if device and tz_offset is not None:
                if device.last_tz_offset is not None and device.last_tz_offset != tz_offset:
                    logger.info("Time zone shift detected for %s: %d -> %d", device_id, device.last_tz_offset, tz_offset)
                    device.tz_shift_active_until = datetime.utcnow() + timedelta(hours=24)
                device.last_tz_offset = tz_offset
                await db.commit()

        # Persist events
        async with async_session() as db:
            for ev in events:
                raw_data = json.dumps(ev.get("data")) if isinstance(ev.get("data"), dict) else ev.get("data")
                encrypted_data = crypto_manager.encrypt(raw_data)
                encrypted_pkg = crypto_manager.encrypt(ev.get("package_name"))
                db.add(BehaviorEvent(
                    device_id=device_id,
                    event_type=ev["event_type"],
                    package_name=encrypted_pkg,
                    timestamp=ev.get("timestamp", 0),
                    data=encrypted_data,
                ))
            await db.commit()

        # Extract features
        feature_vector, feature_mask = self.feature_extractor.extract(events)
        feature_vector = self.baseline_manager.apply_power_transform(device_id, feature_vector)

        # Load baseline
        async with async_session() as db:
            result = await db.execute(select(Device).where(Device.id == device_id))
            device = result.scalar_one_or_none()
            if not device:
                return

            personalized_mean = device.get_baseline_mean()
            personalized_cov = device.get_baseline_covariance()

            baseline_mean, baseline_cov = self.baseline_manager.get_blended_baseline(
                device.first_seen, personalized_mean, personalized_cov
            )

            if personalized_cov is not None:
                generic_mean, generic_cov = self.baseline_manager.get_warm_start_baseline()
                baseline_cov = self.baseline_manager._ensure_psd(baseline_cov, generic_cov)

            if personalized_mean is None or personalized_cov is None:
                logger.info("Initializing baseline structures for new device %s", device_id)
                device.set_baseline_mean(baseline_mean)
                device.set_baseline_covariance(baseline_cov)

            threshold_multiplier = 1.0
            if device.tz_shift_active_until and device.tz_shift_active_until > datetime.utcnow():
                threshold_multiplier = settings.tz_shift_threshold_multiplier
                logger.debug("Applying TZ shift threshold multiplier (%.1f) for %s", threshold_multiplier, device_id)

            # Anomaly detection
            detection = self.anomaly_detector.detect(
                feature_vector=feature_vector,
                baseline_mean=baseline_mean,
                baseline_cov=baseline_cov,
                feature_mask=feature_mask,
                device_id=device_id,
                cusum_pos=device.cusum_pos,
                cusum_neg=device.cusum_neg,
                cusum_h=getattr(device, 'last_cusum_h', None),
                distance_mean=device.distance_mean,
                distance_std=device.distance_std,
            )
            if threshold_multiplier != 1.0:
                detection.threshold *= threshold_multiplier

            rule_alert = self._evaluate_rule_alert(events)

            if rule_alert and not detection.is_anomaly:
                if not await self._should_emit_indicator_alert(device_id, rule_alert):
                    rule_alert = None

            # Ensemble fallback
            ml_signal = {"enabled": False, "ready": False}
            ensemble_mode = str(settings.ml_ensemble_mode).lower()
            should_run_ensemble = False
            if ensemble_mode == "primary":
                should_run_ensemble = True
            elif ensemble_mode == "fallback":
                if detection.threshold > 0:
                    ratio = detection.mahalanobis_distance / detection.threshold
                    should_run_ensemble = 0.8 < ratio < 1.2

            if should_run_ensemble:
                ml_signal = await self._to_thread(self.ml_inference.predict_window, events, feature_vector)

            if bool(ml_signal.get("ensemble_pred")):
                ensemble_score = float(ml_signal.get("ensemble_score", 0.0))
                nsl_score = float(ml_signal.get("nsl_attack_prob", 0.0))
                loghub_score = float(ml_signal.get("loghub_attack_prob", 0.0))
                active_models = ", ".join(ml_signal.get("active_models", [])) or "ensemble"
                ensemble_suffix = f"Ensemble ML ({active_models}) score={ensemble_score:.2f} (nsl={nsl_score:.2f}, loghub={loghub_score:.2f})."

                if detection.is_anomaly:
                    if ensemble_score >= 0.70:
                        detection.severity = min(10, detection.severity + 1)
                    detection.confidence = max(detection.confidence, min(0.99, ensemble_score + 0.12))
                    detection.message = f"{detection.message} | {ensemble_suffix}"
                else:
                    detection.is_anomaly = True
                    detection.severity = max(detection.severity, 7)
                    detection.confidence = max(detection.confidence, min(0.98, ensemble_score + 0.20))
                    if detection.threat_type == ThreatType.NONE:
                        detection.threat_type = ThreatType.DEVICE_MISUSE
                    detection.message = f"Supervised ensemble flagged suspicious behavior. {ensemble_suffix}"

            # Adaptive permission correlation
            has_sensitive_permission = any(
                str(ev.get("event_type", "")).upper() == "PERMISSION_ACCESS"
                and json.loads(ev.get("data", "{}") if isinstance(ev.get("data"), str) else json.dumps(ev.get("data", {}))).get("permission", "").upper() in ("CAMERA", "RECORD_AUDIO", "FINE_LOCATION")
                for ev in events
            )
            if detection.is_anomaly and has_sensitive_permission:
                detection.severity = min(10, detection.severity + 2)
                detection.threat_type = ThreatType.INSIDER_THREAT
                detection.message += " | Escalate: Correlated with sensitive permission access."

            is_suspicious_window = detection.is_anomaly or rule_alert is not None
            idle_duration_seconds = 0
            if device.last_seen:
                idle_duration_seconds = (datetime.utcnow() - device.last_seen).total_seconds()

            drift = False
            cusum_h = settings.cusum_threshold
            if idle_duration_seconds > 600:
                logger.info("Device %s woke up after %d seconds idle. Skipping baseline updates.", device_id, int(idle_duration_seconds))
            else:
                new_pos, new_neg, drift, cusum_h = self.baseline_manager.update_cusum(
                    device.cusum_pos, device.cusum_neg,
                    detection.mahalanobis_distance, device.distance_mean,
                    device_id=device_id,
                )
                device.cusum_pos = new_pos
                device.cusum_neg = new_neg
                device.last_cusum_h = cusum_h
                # Update detection with dynamic h for future classification if needed
                detection.message = detection.message.replace(f"threshold {detection.threshold:.1f}", f"threshold {detection.threshold:.1f} (h={cusum_h:.1f})")

                new_d_mean, new_d_std = self.baseline_manager.update_distance_stats(
                    device.distance_mean, device.distance_std,
                    detection.mahalanobis_distance, device.baseline_sample_count,
                )
                device.distance_mean = new_d_mean
                device.distance_std = new_d_std

            active_threat_type = (
                detection.threat_type.value if detection.is_anomaly else (rule_alert["threat_type"] if rule_alert else "NONE")
            )
            active_severity = detection.severity if detection.is_anomaly else (rule_alert["severity"] if rule_alert else 0)

            should_update = False
            if not is_suspicious_window:
                should_update = True
            elif self.baseline_manager.should_update_after_anomaly(active_threat_type, active_severity):
                should_update = True

            if should_update and idle_duration_seconds <= 600:
                new_mean, new_cov = self.baseline_manager.update_baseline(
                    baseline_mean, baseline_cov,
                    feature_vector, device.baseline_sample_count,
                    drift_detected=drift
                )
                device.set_baseline_mean(new_mean)
                device.set_baseline_covariance(new_cov)
                self.baseline_manager.add_to_refit_buffer(device_id, feature_vector)
                if self.baseline_manager.should_refit(device_id, device.baseline_sample_count):
                    samples = self.baseline_manager.get_buffer_samples(device_id)
                    if samples is not None:
                        logger.info("Periodically refitting Yeo-Johnson transform for %s", device_id)
                        self.baseline_manager.fit_power_transform(samples, device_id)

            device.baseline_sample_count += 1
            # M1: Fit initial power transform after first 100 samples
            if device.baseline_sample_count == 100:
                samples = self.baseline_manager.get_buffer_samples(device_id)
                if samples is not None:
                    logger.info("Fitting initial Yeo-Johnson transform for %s at 100 samples", device_id)
                    self.baseline_manager.fit_power_transform(samples, device_id)

            device.last_seen = datetime.utcnow()
            await db.commit()

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

                if bool(ml_signal.get("ensemble_pred")):
                    alert_source = "model+ensemble" if alert_source == "model" else f"{alert_source}+ensemble"

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
                    ml_signal=ml_signal,
                )

                if detection is not None and detection.feature_contributions:
                    record_anomaly_contributions(device_id, detection.feature_contributions)

                alert = self.alert_manager.create_alert(
                    device_id=device_id,
                    severity=alert_severity,
                    threat_type=alert_threat_type,
                    message=alert_message,
                    confidence=alert_confidence,
                    mahalanobis_distance=alert_distance,
                    anomaly_probability=detection.anomaly_probability if detection else 0.0,
                    target_package=action_targets.get("target_package"),
                    target_uid=action_targets.get("target_uid"),
                    xai_explanation=xai_explanation,
                    feature_vector=feature_vector,
                )

                # Auto‑approve for high‑confidence adware
                if alert_threat_type == "MALWARE_MIMICRY" and alert_confidence > 0.95:
                    executor = ActionExecutor()
                    await executor.execute_all_actions(
                        actions=["kill_process", "quarantine_app"],
                        device_id=device_id,
                        target_package=action_targets.get("target_package"),
                    )
                    alert.status = "approved"
                    alert.action_executed = True

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
                    device_id, alert_source, alert_threat_type, alert_severity, alert_confidence,
                )

    async def _should_emit_indicator_alert(self, device_id: str, rule_alert: Dict[str, Any]) -> bool:
        indicator = str(rule_alert.get("indicator", "")).strip()
        if not indicator:
            return True

        cache_key = f"{device_id}:{indicator.lower()}"
        now_ts = datetime.utcnow().timestamp()
        cooldown = max(0, int(settings.rule_alert_cooldown_seconds))

        async with self._cache_lock:
            last_ts = self._indicator_alert_cache.get(cache_key)
            if last_ts is not None and (now_ts - last_ts) < cooldown:
                return False
            self._indicator_alert_cache[cache_key] = now_ts
            stale_cutoff = now_ts - max(cooldown * 3, 300)
            stale_keys = [key for key, ts in self._indicator_alert_cache.items() if ts < stale_cutoff]
            for key in stale_keys:
                self._indicator_alert_cache.pop(key, None)
            
            # M4: Fixed maximum cache size to prevent memory growth
            if len(self._indicator_alert_cache) > 10000:
                # Remove oldest 1000 entries if limit exceeded
                sorted_items = sorted(self._indicator_alert_cache.items(), key=lambda x: x[1])
                for i in range(min(1000, len(sorted_items))):
                    self._indicator_alert_cache.pop(sorted_items[i][0], None)
        return True

    async def _emit_rule_alert(
        self,
        device_id: str,
        rule_alert: Dict[str, Any],
        events: List[Dict[str, Any]],
        source: str,
    ) -> None:
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
            device_id, source, str(rule_alert["threat_type"]),
            int(rule_alert["severity"]), float(rule_alert["confidence"]),
        )

    async def _check_phishing_fast_path(self, device_id: str, events: List[Dict[str, Any]]) -> None:
        for ev in events:
            if str(ev.get("event_type", "")).upper() != "WEB_DOMAIN":
                continue
            data = self._parse_event_data(ev)
            domain = str(data.get("domain", "")).strip().lower()
            url = data.get("url")
            tflite_score = data.get("tfliteScore")
            if not domain:
                continue
            try:
                tflite_score_float = float(tflite_score) if tflite_score is not None else None
            except (ValueError, TypeError):
                tflite_score_float = None

            result = await self._to_thread(self.phishing_analyzer.analyze, domain, url, tflite_score_float)
            if result.classification == "safe":
                continue

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
            if not await self._should_emit_indicator_alert(device_id, phishing_alert):
                continue
            logger.warning(
                "PHISHING detected: device=%s domain=%s score=%.2f brand=%s reasons=%s",
                device_id, domain, result.risk_score, result.matched_brand, result.reasons,
            )
            await self._emit_rule_alert(device_id, phishing_alert, events, source="phishing-analyzer")

    async def _check_permission_fast_path(self, device_id: str, events: List[Dict[str, Any]]) -> None:
        for ev in events:
            if str(ev.get("event_type", "")).upper() != "PERMISSION_ACCESS":
                continue
            data = self._parse_event_data(ev)
            permission = str(data.get("permission", "")).upper()
            is_side_loaded = bool(data.get("isSideLoaded", False))
            pkg = str(data.get("packageName", ev.get("package_name", "unknown")))
            if not is_side_loaded:
                continue
            if permission not in ("CAMERA", "RECORD_AUDIO", "FINE_LOCATION", "COARSE_LOCATION"):
                continue

            if permission in ("CAMERA", "RECORD_AUDIO"):
                severity = 8
                threat_type = "INSIDER_THREAT"
                perm_label = permission.lower().replace("_", " ")
                message = f"⚠ Side-loaded app '{pkg}' accessed {perm_label} — potential surveillance risk"
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
            if not await self._should_emit_indicator_alert(device_id, perm_alert):
                continue
            logger.warning(
                "PERMISSION alert: device=%s pkg=%s perm=%s sideLoaded=%s",
                device_id, pkg, permission, is_side_loaded,
            )
            await self._emit_rule_alert(device_id, perm_alert, events, source="permission-monitor")

    async def _check_canary_fast_path(self, device_id: str, events: List[Dict[str, Any]]) -> None:
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
            if not await self._should_emit_indicator_alert(device_id, canary_alert):
                continue
            logger.critical(
                "CANARY TRIGGERED: device=%s file=%s action=%s",
                device_id, file_name, action,
            )
            await self._emit_rule_alert(device_id, canary_alert, events, source="canary-manager")

    # ---------- Static Helper Methods ----------
    @staticmethod
    def _window_span_seconds(events: List[Dict[str, Any]]) -> Optional[float]:
        timestamps: List[float] = []
        for ev in events:
            raw = ev.get("timestamp")
            try:
                ts = float(raw)
            except (TypeError, ValueError):
                continue
            if ts <= 0:
                continue
            if ts > 10_000_000_000:
                ts /= 1000.0
            timestamps.append(ts)
        if len(timestamps) < 2:
            return None
        span = max(timestamps) - min(timestamps)
        return round(max(span, 0.0), 3)

    @staticmethod
    def _top_event_types(events: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
        counts: Counter[str] = Counter(str(ev.get("event_type", "UNKNOWN")).upper() for ev in events)
        return [{"event_type": event_type, "count": count} for event_type, count in counts.most_common(max(limit, 1))]

    @staticmethod
    def _dominant_package(events: List[Dict[str, Any]]) -> Optional[str]:
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
        ml_signal: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        event_count = len(events)
        span_seconds = ConnectionManager._window_span_seconds(events)
        top_event_types = ConnectionManager._top_event_types(events, limit=3)
        dominant_package = ConnectionManager._dominant_package(events)
        indicator = str(rule_alert.get("indicator", "")).strip() if rule_alert else ""

        threshold_value = (
            float(selected_threshold) if selected_threshold is not None
            else (float(detection.threshold) if detection is not None else 0.0)
        )
        has_model_context = detection is not None and threshold_value > 0
        distance_ratio = round(float(selected_distance) / threshold_value, 3) if has_model_context else None

        if has_model_context and distance_ratio is not None:
            summary = (
                f"{selected_threat_type} risk: {event_count} events in this window; "
                f"distance {selected_distance:.2f} vs threshold {threshold_value:.2f} "
                f"({distance_ratio:.2f}x), confidence {selected_confidence:.2f}."
            )
        elif indicator:
            summary = f"{selected_threat_type} risk: matched indicator {indicator} across {event_count} recent events (confidence {selected_confidence:.2f})."
        else:
            summary = f"{selected_threat_type} risk: {event_count} recent events triggered security rules (confidence {selected_confidence:.2f})."

        factors: List[str] = []
        if has_model_context and distance_ratio is not None:
            factors.append(f"Model anomaly score crossed threshold ({selected_distance:.2f} > {threshold_value:.2f}).")
            if detection and hasattr(detection, "feature_contributions") and detection.feature_contributions:
                factors.extend(explain_feature_contributions(detection.feature_contributions))

        ml_context: Optional[Dict[str, Any]] = None
        if ml_signal and bool(ml_signal.get("ready")):
            ensemble_score = float(ml_signal.get("ensemble_score", 0.0))
            nsl_score = float(ml_signal.get("nsl_attack_prob", 0.0))
            loghub_score = float(ml_signal.get("loghub_attack_prob", 0.0))
            active_models = list(ml_signal.get("active_models", []))
            ml_context = {
                "active_models": active_models,
                "nsl_attack_prob": round(nsl_score, 4),
                "loghub_attack_prob": round(loghub_score, 4),
                "ensemble_score": round(ensemble_score, 4),
                "ensemble_pred": bool(ml_signal.get("ensemble_pred", False)),
            }
            factors.append(f"Supervised ensemble score {ensemble_score:.2f} (nsl={nsl_score:.2f}, loghub={loghub_score:.2f}).")
            if bool(ml_signal.get("ensemble_pred", False)):
                factors.append("Ensemble threshold exceeded, increasing attack recall sensitivity.")

        if indicator:
            factors.append(f"Matched configured threat indicator: {indicator}.")
        if dominant_package:
            factors.append(f"Dominant package in window: {dominant_package}.")
        if top_event_types:
            compact_types = ", ".join(f"{item['event_type']} x{item['count']}" for item in top_event_types)
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
                "ensemble": ml_context,
            },
            "rule": {
                "indicator": indicator or None,
                "rule_message": str(rule_alert.get("message", "")) if rule_alert else None,
            },
        }

    @staticmethod
    def _parse_event_data(event: Dict[str, Any]) -> Dict[str, Any]:
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
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _extract_action_targets(events: list) -> Dict[str, Optional[Any]]:
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

        target_package = max(package_counts.items(), key=lambda kv: kv[1])[0] if package_counts else None
        target_uid = max(uid_scores.items(), key=lambda kv: kv[1])[0] if uid_scores else None
        return {"target_package": target_package, "target_uid": target_uid}

    @staticmethod
    def _evaluate_rule_alert(events: list) -> Optional[Dict[str, Any]]:
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
            normalized_packages = []
            for candidate in package_candidates:
                if isinstance(candidate, str) and candidate.strip():
                    normalized_packages.append(candidate.strip().lower())

            if normalized_packages and all(
                ConnectionManager._is_ignored_package(pkg, ignored_packages) for pkg in normalized_packages
            ):
                continue

            for pkg in normalized_packages:
                if not ConnectionManager._is_ignored_package(pkg, ignored_packages):
                    observed_packages.add(pkg)

            domain_candidates = [data.get("domain"), data.get("host"), data.get("url"), data.get("dstHost")]
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
        rule_alert: Optional[Dict[str, Any]] = None

        logger.info("Rule check: malicious_apps=%s, observed=%s", malicious_apps, observed_packages)
        if observed_packages:
            logger.info("Observed packages in window: %s", ", ".join(sorted(observed_packages)))
        for pkg in sorted(observed_packages):
            if pkg in malicious_apps:
                candidate = {
                    "severity": 9,
                    "threat_type": "MALWARE_MIMICRY",
                    "message": f"Known malicious app activity detected: {pkg}",
                    "confidence": 0.97,
                    "indicator": f"app:{pkg}",
                    "target_package": pkg,
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
                "message": f"High network burst ({total_network_mb:.1f} MB) during system stress (low_memory={low_memory_events}, battery_critical={battery_critical_events})",
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

        # Permission rules
        permission_events = [ev for ev in events if str(ev.get("event_type", "")).upper() == "PERMISSION_ACCESS"]
        for ev in permission_events:
            data = ConnectionManager._parse_event_data(ev)
            permission = str(data.get("permission", "")).upper()
            is_side_loaded = bool(data.get("isSideLoaded", False))
            pkg = str(data.get("packageName", ev.get("package_name", "unknown")))
            if is_side_loaded and permission in ("CAMERA", "RECORD_AUDIO"):
                candidate = {
                    "severity": 8,
                    "threat_type": "INSIDER_THREAT",
                    "message": f"Side-loaded app '{pkg}' accessed {permission.lower().replace('_', ' ')} — potential surveillance risk",
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
                    "message": f"Side-loaded app '{pkg}' accessed location data",
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
                    "message": f"Third-party app '{pkg}' accessed {permission.lower().replace('_', ' ')}",
                    "confidence": 0.65,
                }
                if rule_alert is None or candidate["severity"] >= rule_alert["severity"]:
                    rule_alert = candidate

        return rule_alert

    @staticmethod
    def _parse_csv_setting(raw_value: str) -> set[str]:
        return {token.strip().lower() for token in str(raw_value or "").split(",") if token.strip()}

    @staticmethod
    def _is_ignored_device(device_id: str) -> bool:
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
        normalized = str(package_name or "").strip().lower()
        if not normalized:
            return False
        blocked = ignored_packages if ignored_packages is not None else ConnectionManager._parse_csv_setting(settings.ignored_alert_packages)
        return normalized in blocked

    @staticmethod
    def _normalize_domain(value: Any) -> Optional[str]:
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
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
            return None
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", host):
            return None
        return host

    @staticmethod
    def _is_malicious_domain(domain: str, blocked_domains: set[str]) -> bool:
        normalized = ConnectionManager._normalize_domain(domain)
        if not normalized:
            return False
        for blocked in blocked_domains:
            if normalized == blocked or normalized.endswith(f".{blocked}"):
                return True
        return False

        device.last_seen = datetime.utcnow()
        await db.commit()