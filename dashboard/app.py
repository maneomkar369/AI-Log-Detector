"""Flask + Socket.IO dashboard with live ADB logcat and detection controls."""

import json
import os
import re
import select
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json_like(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _extract_xai_data(alert: Dict[str, Any]) -> Dict[str, Any]:
    """Extract best-effort XAI summary and factors from alert payloads."""
    explanation = alert.get("xai_explanation", alert.get("xaiExplanation"))
    parsed = _parse_json_like(explanation)
    return {
        "summary": str(parsed.get("summary", "")).strip() or None,
        "factors": parsed.get("factors", []) if isinstance(parsed.get("factors"), list) else []
    }


def _parse_datetime_from_record(record: Dict[str, Any]) -> datetime:
    for key in ("timestamp", "created_at", "_received"):
        raw = record.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 10_000_000_000:
                ts /= 1000.0
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (ValueError, OSError):
                continue
        if isinstance(raw, str):
            normalized = raw.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(normalized)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


def _severity_label(score: int) -> str:
    if score >= 9:
        return "critical"
    if score >= 7:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _build_dashboard_csp() -> str:
    """Build a strict CSP with an optional unsafe-eval escape hatch."""
    script_sources = [
        "'self'",
        "https://cdnjs.cloudflare.com",
        "https://cdn.jsdelivr.net",
    ]
    if _env_bool("DASHBOARD_CSP_ALLOW_UNSAFE_EVAL", default=False):
        script_sources.append("'unsafe-eval'")

    directives = {
        "default-src": ["'self'"],
        "base-uri": ["'self'"],
        "frame-ancestors": ["'self'"],
        "object-src": ["'none'"],
        "script-src": script_sources,
        "style-src": ["'self'", "https://fonts.googleapis.com"],
        "font-src": ["'self'", "https://fonts.gstatic.com", "data:"],
        "img-src": ["'self'", "data:"],
        # Include CDN hosts so browser source-map fetches for third-party scripts
        # do not raise CSP violations in the console.
        "connect-src": [
            "'self'",
            "ws:",
            "wss:",
            "https://cdnjs.cloudflare.com",
            "https://cdn.jsdelivr.net",
        ],
    }

    return "; ".join(
        f"{directive} {' '.join(sources)}" for directive, sources in directives.items()
    )


def _classify_ioc_alert(alert: Dict[str, Any]) -> Optional[str]:
    """Return IOC type for alert rows when known indicator context is present."""
    indicator = str(alert.get("indicator", "")).strip().lower()
    if indicator.startswith("app:"):
        return "app"
    if indicator.startswith("domain:"):
        return "domain"
    if indicator.startswith("phishing:"):
        return "phishing"
    if indicator.startswith("perm:"):
        return "permission"

    threat_type = str(alert.get("threat_type", alert.get("threatType", ""))).upper()
    if threat_type == "PHISHING":
        return "phishing"

    message = str(alert.get("message", "")).strip().lower()
    if "known malicious app activity detected" in message:
        return "app"
    if "known malicious website detected" in message:
        return "domain"
    if "phishing" in message or "suspicious website" in message:
        return "phishing"
    if "permission" in message and ("camera" in message or "microphone" in message or "location" in message):
        return "permission"

    return None


def _alert_identity(alert: Dict[str, Any]) -> str:
    value = alert.get("anomalyId", alert.get("anomaly_id", ""))
    return str(value or "").strip()


def _upsert_alert(recent_alerts: List[Dict[str, Any]], alert: Dict[str, Any], max_alerts: int) -> None:
    """Upsert alert snapshots by anomaly id so status updates replace existing entries."""
    alert_id = _alert_identity(alert)

    if alert_id:
        for idx, existing in enumerate(recent_alerts):
            if _alert_identity(existing) == alert_id:
                merged = {**existing, **alert}
                recent_alerts.pop(idx)
                recent_alerts.append(merged)
                if len(recent_alerts) > max_alerts:
                    recent_alerts.pop(0)
                return

    recent_alerts.append(alert)
    if len(recent_alerts) > max_alerts:
        recent_alerts.pop(0)


def _event_severity_score(event: Dict[str, Any]) -> int:
    severity = event.get("severity")
    if isinstance(severity, (int, float)):
        return max(1, min(int(severity), 10))

    event_type = str(event.get("event_type", "")).upper()
    if event_type.startswith("SECURITY_"):
        return 7
    if event_type.startswith("NETWORK_FLOW"):
        return 6
    if event_type.startswith("NETWORK"):
        return 5
    if event_type.startswith("SYSTEM"):
        return 4
    return 2


def _is_auth_failure(event: Dict[str, Any]) -> bool:
    event_type = str(event.get("event_type", "")).upper()
    if "AUTH_FAIL" in event_type or "LOGIN_FAIL" in event_type:
        return True
    if event_type == "SECURITY_AUTH_EVENT":
        payload = _parse_json_like(event.get("data"))
        token = str(payload.get("event", payload.get("status", ""))).upper()
        if any(keyword in token for keyword in ("FAIL", "DENIED", "LOCK", "ERROR")):
            return True
        raw = str(event.get("data", "")).upper()
        return any(keyword in raw for keyword in ("FAIL", "DENIED", "LOCK", "ERROR"))
    return False


class AdbLogStreamer:
    """Background worker that streams adb logcat and emits Socket.IO events."""

    LOG_RE = re.compile(
        r"^(?P<date>\d{2}-\d{2})\s+"
        r"(?P<time>\d{2}:\d{2}:\d{2}\.\d+)\s+"
        r"(?P<pid>\d+)\s+"
        r"(?P<tid>\d+)\s+"
        r"(?P<level>[VDIWEAF])\s+"
        r"(?P<tag>[^:]+):\s?(?P<message>.*)$"
    )

    BUFFER_CHOICES = {"all", "main", "system", "events", "radio", "crash"}

    def __init__(self, socketio: SocketIO):
        self.socketio = socketio
        self.lock = threading.Lock()
        self.config: Dict[str, Any] = {
            "buffer": os.getenv("ADB_LOGCAT_BUFFER", "all"),
            "buffer_size_kb": int(os.getenv("ADB_BUFFER_SIZE_KB", "256")),
            "poll_interval_ms": int(os.getenv("ADB_POLL_INTERVAL_MS", "400")),
            "package_filter": os.getenv("ADB_PACKAGE_FILTER", ""),
        }
        self.status: Dict[str, Any] = {
            "connected": False,
            "state": "initializing",
            "message": "Starting ADB monitor",
            "last_error": "",
            "last_updated": _utcnow_iso(),
        }
        self.command_state: Dict[str, Any] = {
            "commands": [],
            "last_executed": _utcnow_iso(),
        }
        self.retry_initial_seconds = max(0.5, float(os.getenv("ADB_RETRY_INITIAL_SECONDS", "1.0")))
        self.retry_max_seconds = max(
            self.retry_initial_seconds,
            float(os.getenv("ADB_RETRY_MAX_SECONDS", "10.0")),
        )
        self._retry_delay_seconds = self.retry_initial_seconds
        self._next_retry_at = 0.0
        self.current_buffer_hint = self.config["buffer"]
        self.logs: deque = deque(maxlen=1500)
        self.stop_event = threading.Event()
        self.restart_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.restart_event.set()

    def get_recent_logs(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.lock:
            capped_limit = max(1, min(limit, 1000))
            return list(self.logs)[-capped_limit:]

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                **self.status,
                "config": dict(self.config),
                "commands": list(self.command_state["commands"]),
                "commands_updated": self.command_state["last_executed"],
            }

    def update_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            if "buffer" in payload:
                buffer_name = str(payload["buffer"]).lower().strip()
                if buffer_name in self.BUFFER_CHOICES:
                    self.config["buffer"] = buffer_name
            if "buffer_size_kb" in payload:
                try:
                    size = int(payload["buffer_size_kb"])
                    self.config["buffer_size_kb"] = max(64, min(size, 4096))
                except (TypeError, ValueError):
                    pass
            if "poll_interval_ms" in payload:
                try:
                    interval = int(payload["poll_interval_ms"])
                    self.config["poll_interval_ms"] = max(150, min(interval, 5000))
                except (TypeError, ValueError):
                    pass
            if "package_filter" in payload:
                self.config["package_filter"] = str(payload["package_filter"]).strip()

        self.restart_event.set()
        return self.get_status()

    def _set_status(self, connected: bool, state: str, message: str, last_error: str = "") -> None:
        with self.lock:
            self.status = {
                "connected": connected,
                "state": state,
                "message": message,
                "last_error": last_error,
                "last_updated": _utcnow_iso(),
            }
            payload = {
                **self.status,
                "config": dict(self.config),
                "commands": list(self.command_state["commands"]),
                "commands_updated": self.command_state["last_executed"],
            }
        self.socketio.emit("adb_status", payload)

    def _set_commands(self, logcat_cmd: List[str]) -> None:
        with self.lock:
            package_filter = self.config["package_filter"]
            command_preview = " ".join(logcat_cmd)
            if package_filter:
                command_preview = f'{command_preview} | grep -i "{package_filter}"'
            self.command_state = {
                "commands": [
                    "adb get-state",
                    f"adb logcat -G {self.config['buffer_size_kb']}K",
                    command_preview,
                ],
                "last_executed": _utcnow_iso(),
            }

    def _build_logcat_command(self) -> List[str]:
        with self.lock:
            buffer_name = self.config["buffer"]
        return ["adb", "logcat", "-v", "threadtime", "-b", buffer_name]

    def _apply_buffer_size(self) -> None:
        with self.lock:
            size = self.config["buffer_size_kb"]
        try:
            subprocess.run(
                ["adb", "logcat", "-G", f"{size}K"],
                capture_output=True,
                text=True,
                timeout=2.5,
                check=False,
            )
        except Exception:
            # Best-effort only; unsupported devices can ignore this.
            pass

    def _check_device_state(self) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                ["adb", "get-state"],
                capture_output=True,
                text=True,
                timeout=2.5,
                check=False,
            )
        except FileNotFoundError:
            return {
                "connected": False,
                "state": "adb_missing",
                "message": "adb command not found in PATH",
            }
        except subprocess.TimeoutExpired:
            return {
                "connected": False,
                "state": "timeout",
                "message": "adb get-state timeout",
            }

        raw_state = (result.stdout or result.stderr or "").strip()
        state = raw_state.lower()
        if result.returncode == 0 and state == "device":
            return {
                "connected": True,
                "state": "device",
                "message": "ADB device connected",
            }

        if (
            "host.docker.internal:5037" in state
            and (
                "network is unreachable" in state
                or "no route to host" in state
                or "name or service not known" in state
            )
        ):
            return {
                "connected": False,
                "state": "adb_bridge_unreachable",
                "message": (
                    "Cannot reach host.docker.internal:5037 from container. "
                    "Set ADB_SERVER_SOCKET=tcp:<host-ip>:5037 or verify host-gateway mapping."
                ),
            }

        if not state:
            state = "disconnected"
        return {
            "connected": False,
            "state": state,
            "message": f"ADB state: {state}",
        }

    def _reset_retry_backoff(self) -> None:
        self._retry_delay_seconds = self.retry_initial_seconds
        self._next_retry_at = 0.0

    def _schedule_retry(self) -> None:
        self._next_retry_at = time.monotonic() + self._retry_delay_seconds
        self._retry_delay_seconds = min(self._retry_delay_seconds * 2.0, self.retry_max_seconds)

    def _terminate_process(self, process: Optional[subprocess.Popen]) -> Optional[subprocess.Popen]:
        if process is None:
            return None
        try:
            process.terminate()
            process.wait(timeout=1.5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        return None

    def _handle_log_line(self, raw_line: str) -> None:
        line = raw_line.strip("\n")
        if not line:
            return

        lower_line = line.lower()
        if lower_line.startswith("--------- beginning of"):
            parts = line.split()
            if parts:
                self.current_buffer_hint = parts[-1].strip()
            return

        with self.lock:
            package_filter = self.config["package_filter"].lower().strip()
            configured_buffer = self.config["buffer"]

        if package_filter and package_filter not in lower_line:
            return

        match = self.LOG_RE.match(line)
        if match:
            severity = match.group("level")
            pid_raw = match.group("pid")
            tag = match.group("tag").strip()
            message = match.group("message")
            try:
                pid_value: Optional[int] = int(pid_raw)
            except ValueError:
                pid_value = None
        else:
            severity = "I"
            pid_value = None
            tag = "(raw)"
            message = line

        buffer_value = self.current_buffer_hint if configured_buffer == "all" else configured_buffer
        entry = {
            "timestamp": _utcnow_iso(),
            "buffer": buffer_value,
            "pid": pid_value,
            "tag": tag,
            "message": message,
            "severity": severity,
            "raw": line,
        }

        with self.lock:
            self.logs.append(entry)

        self.socketio.emit("adb_log", entry)

    def _run(self) -> None:
        process: Optional[subprocess.Popen] = None
        status_refresh_every = 2.0
        last_status_check = 0.0

        while not self.stop_event.is_set():
            if self.restart_event.is_set():
                self.restart_event.clear()
                process = self._terminate_process(process)
                self._reset_retry_backoff()

            now = time.monotonic()
            if now < self._next_retry_at:
                self.stop_event.wait(min(0.5, self._next_retry_at - now))
                continue

            if now - last_status_check >= status_refresh_every or process is None:
                probe = self._check_device_state()
                if not probe["connected"]:
                    self._set_status(False, probe["state"], probe["message"], probe["message"])
                    process = self._terminate_process(process)
                    last_status_check = now
                    self._schedule_retry()
                    continue

                self._set_status(True, probe["state"], probe["message"])
                last_status_check = now
                self._reset_retry_backoff()

            if process is None:
                self._apply_buffer_size()
                logcat_cmd = self._build_logcat_command()
                self._set_commands(logcat_cmd)

                try:
                    process = subprocess.Popen(
                        logcat_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                    )
                    self._set_status(True, "streaming", "Streaming adb logcat")
                    self._reset_retry_backoff()
                except Exception as exc:
                    self._set_status(False, "logcat_error", "Failed to start adb logcat", str(exc))
                    self._schedule_retry()
                    continue

            poll_interval = self.get_status()["config"]["poll_interval_ms"] / 1000.0
            stdout = process.stdout
            if stdout is None:
                process = self._terminate_process(process)
                continue

            try:
                ready, _, _ = select.select([stdout], [], [], poll_interval)
            except (OSError, ValueError):
                process = self._terminate_process(process)
                continue

            if ready:
                line = stdout.readline()
                if line:
                    self._handle_log_line(line)
                else:
                    process = self._terminate_process(process)

            if process is not None and process.poll() is not None:
                process = self._terminate_process(process)
                self._set_status(False, "restarting", "adb logcat exited; retrying")
                self._schedule_retry()

        self._terminate_process(process)


def _build_dashboard_summary(recent_events: List[Dict[str, Any]], recent_alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    day_list = [today - timedelta(days=idx) for idx in range(6, -1, -1)]
    day_to_index = {day: idx for idx, day in enumerate(day_list)}

    trend = {
        "labels": [day.strftime("%b %d") for day in day_list],
        "anomalies": [0] * 7,
        "critical": [0] * 7,
        "network": [0] * 7,
        "auth_failures": [0] * 7,
    }

    anomalies_total = len(recent_alerts)
    critical_total = 0
    network_total = 0
    auth_failure_total = 0
    ioc_total = 0
    ioc_app_total = 0
    ioc_domain_total = 0
    phishing_total = 0
    permission_total = 0

    today_distribution = {
        "anomalies": 0,
        "critical": 0,
        "network": 0,
        "auth_failures": 0,
    }

    alert_rows: List[Dict[str, Any]] = []
    event_rows: List[Dict[str, Any]] = []

    for alert in recent_alerts:
        dt = _parse_datetime_from_record(alert)
        day = dt.date()
        severity = int(alert.get("severity", 0) or 0)
        threat_type = str(alert.get("threat_type", alert.get("threatType", "ANOMALY")))
        device_id = str(alert.get("device_id", alert.get("deviceId", "-")))
        ioc_type = _classify_ioc_alert(alert)

        idx = day_to_index.get(day)
        if idx is not None:
            trend["anomalies"][idx] += 1
            if severity >= 9:
                trend["critical"][idx] += 1

        if severity >= 9:
            critical_total += 1

        if ioc_type == "app":
            ioc_total += 1
            ioc_app_total += 1
        elif ioc_type == "domain":
            ioc_total += 1
            ioc_domain_total += 1
        elif ioc_type == "phishing":
            ioc_total += 1
            phishing_total += 1
        elif ioc_type == "permission":
            permission_total += 1

        if day == today:
            today_distribution["anomalies"] += 1
            if severity >= 9:
                today_distribution["critical"] += 1

        xai_data = _extract_xai_data(alert)
        alert_rows.append(
            {
                "time": dt.isoformat(),
                "source": "ALERT",
                "device_id": device_id,
                "event_type": threat_type,
                "message": str(alert.get("message", "No message")),
                "xai_summary": xai_data["summary"],
                "xai_factors": xai_data["factors"],
                "severity_score": severity,
                "severity": _severity_label(severity),
                "ioc_type": ioc_type or "none",
            }
        )

    for event in recent_events:
        dt = _parse_datetime_from_record(event)
        day = dt.date()
        event_type = str(event.get("event_type", event.get("type", "UNKNOWN"))).upper()
        score = _event_severity_score(event)

        is_network = event_type.startswith("NETWORK")
        is_auth_failure = _is_auth_failure(event)

        idx = day_to_index.get(day)
        if idx is not None:
            if is_network:
                trend["network"][idx] += 1
            if is_auth_failure:
                trend["auth_failures"][idx] += 1

        if is_network:
            network_total += 1
            if day == today:
                today_distribution["network"] += 1

        if is_auth_failure:
            auth_failure_total += 1
            if day == today:
                today_distribution["auth_failures"] += 1

        payload = _parse_json_like(event.get("data"))
        payload_preview = json.dumps(payload) if payload else str(event.get("data", ""))
        event_rows.append(
            {
                "time": dt.isoformat(),
                "source": "EVENT",
                "device_id": event.get("device_id", "-"),
                "event_type": event_type,
                "message": payload_preview[:180] if payload_preview else "No payload",
                "severity_score": score,
                "severity": _severity_label(score),
                "ioc_type": "none",
            }
        )

    # Keep alert visibility stable under heavy event volume.
    combined_rows = sorted(
        alert_rows[:10] + event_rows[:20],
        key=lambda row: row["time"],
        reverse=True,
    )

    return {
        "metrics": {
            "total_anomalies": anomalies_total,
            "critical_alerts": critical_total,
            "network_events": network_total,
            "auth_failures": auth_failure_total,
            "ioc_alerts": ioc_total,
            "ioc_app_alerts": ioc_app_total,
            "ioc_domain_alerts": ioc_domain_total,
            "phishing_alerts": phishing_total,
            "permission_alerts": permission_total,
        },
        "trend": trend,
        "today_distribution": today_distribution,
        "recent_events": combined_rows,
    }


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("DASHBOARD_SECRET_KEY", "dev-secret")

    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")

    recent_events: List[Dict[str, Any]] = []
    recent_alerts: List[Dict[str, Any]] = []
    event_lock = threading.Lock()
    max_events = 1000
    max_alerts = 250

    dashboard_settings: Dict[str, Any] = {
        "detect_crash": True,
        "auth_threshold": "5",
        "detect_cleartext_network": True,
        "memory_anomaly_level": "medium",
        "sqlite_logging": True,
        "ml_scoring": True,
        "export_format": "json",
    }
    profile_state: Dict[str, str] = {"active": "Development"}

    adb_streamer = AdbLogStreamer(socketio)

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("Content-Security-Policy", _build_dashboard_csp())
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/alerts")
    def alerts_page():
        return render_template("alerts.html")

    @app.route("/api/dashboard/events")
    def api_events():
        with event_lock:
            return jsonify(recent_events[-200:])

    @app.route("/api/dashboard/alerts")
    def api_alerts():
        with event_lock:
            return jsonify(recent_alerts[-100:])

    @app.route("/api/dashboard/summary")
    def api_dashboard_summary():
        with event_lock:
            payload = _build_dashboard_summary(recent_events, recent_alerts)
        return jsonify(payload)

    @app.route("/api/adb/status")
    def api_adb_status():
        return jsonify(adb_streamer.get_status())

    @app.route("/api/adb/logs")
    def api_adb_logs():
        try:
            limit = int(request.args.get("limit", "250"))
        except ValueError:
            limit = 250
        return jsonify(adb_streamer.get_recent_logs(limit))

    @app.route("/api/adb/config", methods=["POST"])
    def api_update_adb_config():
        payload = request.get_json(silent=True) or {}
        updated = adb_streamer.update_config(payload)
        return jsonify(updated)

    @app.route("/api/dashboard/settings", methods=["GET", "POST"])
    def api_dashboard_settings():
        nonlocal dashboard_settings
        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            merged = {**dashboard_settings, **payload}
            dashboard_settings = merged
        return jsonify(
            {
                "settings": dashboard_settings,
                "active_profile": profile_state["active"],
            }
        )

    @app.route("/api/dashboard/profile", methods=["POST"])
    def api_dashboard_profile():
        payload = request.get_json(silent=True) or {}
        profile_name = str(payload.get("name", "")).strip()
        if profile_name:
            profile_state["active"] = profile_name
        return jsonify({"active_profile": profile_state["active"]})

    @socketio.on("connect")
    def handle_connect():
        print(f"[Dashboard] Client connected: {request.sid}")

    @socketio.on("disconnect")
    def handle_disconnect():
        print(f"[Dashboard] Client disconnected: {request.sid}")

    def redis_listener() -> None:
        try:
            import redis as redis_lib

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            redis_client = redis_lib.from_url(redis_url)
            pubsub = redis_client.pubsub()
            pubsub.subscribe("events", "alerts")
            print("[Dashboard] Redis subscriber started")

            for message in pubsub.listen():
                if message.get("type") != "message":
                    continue

                channel = message.get("channel")
                if isinstance(channel, bytes):
                    channel = channel.decode()

                try:
                    data = json.loads(message.get("data", "{}"))
                except json.JSONDecodeError:
                    continue

                data["_received"] = _utcnow_iso()

                if channel == "events":
                    with event_lock:
                        recent_events.append(data)
                        if len(recent_events) > max_events:
                            recent_events.pop(0)
                    socketio.emit("new_event", data)
                elif channel == "alerts":
                    with event_lock:
                        _upsert_alert(recent_alerts, data, max_alerts)
                    socketio.emit("new_alert", data)

        except Exception as exc:
            print(f"[Dashboard] Redis subscriber error: {exc}")
            print("[Dashboard] Running without live Redis updates")

    listener_thread = threading.Thread(target=redis_listener, daemon=True)
    listener_thread.start()

    return app, socketio


if __name__ == "__main__":
    app, socketio = create_app()
    port = int(os.getenv("DASHBOARD_PORT", 5000))
    print(f"\n{'=' * 50}")
    print("  ANOMALY DETECTOR DASHBOARD")
    print(f"  http://localhost:{port}")
    print(f"{'=' * 50}\n")
    socketio.run(app, host="0.0.0.0", port=port, debug=True)
