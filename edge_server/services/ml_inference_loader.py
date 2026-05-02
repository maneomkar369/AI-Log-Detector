"""
Runtime loader for supervised ML ensemble inference.

This service loads trained model artifacts (NSL-KDD random-forest pipeline
and LogHub text classifier) and combines their risk scores using a weighted
ensemble aimed at higher recall for demo/security scenarios.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from config import settings

try:
    import joblib
except Exception:  # pragma: no cover - dependency availability varies by runtime
    joblib = None

try:
    import pandas as pd
except Exception:  # pragma: no cover - dependency availability varies by runtime
    pd = None


logger = logging.getLogger(__name__)


NSL_KDD_FEATURE_COLUMNS = [
    "duration",
    "protocol_type",
    "service",
    "flag",
    "src_bytes",
    "dst_bytes",
    "land",
    "wrong_fragment",
    "urgent",
    "hot",
    "num_failed_logins",
    "logged_in",
    "num_compromised",
    "root_shell",
    "su_attempted",
    "num_root",
    "num_file_creations",
    "num_shells",
    "num_access_files",
    "num_outbound_cmds",
    "is_host_login",
    "is_guest_login",
    "count",
    "srv_count",
    "serror_rate",
    "srv_serror_rate",
    "rerror_rate",
    "srv_rerror_rate",
    "same_srv_rate",
    "diff_srv_rate",
    "srv_diff_host_rate",
    "dst_host_count",
    "dst_host_srv_count",
    "dst_host_same_srv_rate",
    "dst_host_diff_srv_rate",
    "dst_host_same_src_port_rate",
    "dst_host_srv_diff_host_rate",
    "dst_host_serror_rate",
    "dst_host_srv_serror_rate",
    "dst_host_rerror_rate",
    "dst_host_srv_rerror_rate",
]


class EnsembleInferenceLoader:
    """Load and evaluate ensemble model artifacts for live inference."""

    def __init__(self) -> None:
        self.enabled = bool(settings.ml_ensemble_enabled)
        self.ready = False
        self._base_dir = Path(__file__).resolve().parents[1]

        self._nsl_pipeline = None
        self._loghub_pipeline = None

        self._weights = {
            "nsl": max(0.0, float(settings.ml_ensemble_weight_nsl)),
            "loghub": max(0.0, float(settings.ml_ensemble_weight_loghub)),
        }
        self._thresholds = {
            "nsl": float(settings.ml_nsl_attack_threshold),
            "loghub": float(settings.ml_loghub_attack_threshold),
            "ensemble": float(settings.ml_ensemble_threshold),
        }

        if not self.enabled:
            logger.info("ML ensemble inference is disabled by configuration")
            return

        if joblib is None or pd is None:
            logger.warning(
                "ML ensemble dependencies missing (joblib/pandas). "
                "Live supervised inference disabled."
            )
            return

        self._load_ensemble_config()
        self._load_models()

    def predict_window(self, events: List[Dict[str, Any]], feature_vector: np.ndarray) -> Dict[str, Any]:
        """Return model scores and final ensemble decision for one event window."""
        result = {
            "enabled": self.enabled,
            "ready": self.ready,
            "active_models": [],
            "nsl_attack_prob": 0.0,
            "loghub_attack_prob": 0.0,
            "ensemble_score": 0.0,
            "nsl_pred": False,
            "loghub_pred": False,
            "ensemble_pred": False,
        }

        if not self.enabled or not self.ready:
            return result

        try:
            nsl_prob = self._predict_nsl_attack_prob(events, feature_vector)
            loghub_prob = self._predict_loghub_attack_prob(events)

            if nsl_prob is not None:
                result["nsl_attack_prob"] = round(float(nsl_prob), 4)
                result["nsl_pred"] = bool(nsl_prob >= self._thresholds["nsl"])
                result["active_models"].append("nsl-rf")

            if loghub_prob is not None:
                result["loghub_attack_prob"] = round(float(loghub_prob), 4)
                result["loghub_pred"] = bool(loghub_prob >= self._thresholds["loghub"])
                result["active_models"].append("loghub-text")

            if not result["active_models"]:
                return result

            ensemble_score = self._combine_scores(nsl_prob, loghub_prob)
            result["ensemble_score"] = round(float(ensemble_score), 4)
            result["ensemble_pred"] = bool(
                ensemble_score >= self._thresholds["ensemble"]
                or result["nsl_pred"]
                or result["loghub_pred"]
            )
            return result
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            logger.warning("ML ensemble inference failed for window: %s", exc)
            return result

    def _load_models(self) -> None:
        self._nsl_pipeline = self._safe_load_model(settings.ml_nsl_model_path, label="nsl-rf")
        self._loghub_pipeline = self._safe_load_model(settings.ml_loghub_model_path, label="loghub-text")
        self.ready = self._nsl_pipeline is not None or self._loghub_pipeline is not None

        if self.ready:
            logger.info(
                "ML ensemble loader ready (nsl=%s, loghub=%s)",
                self._nsl_pipeline is not None,
                self._loghub_pipeline is not None,
            )
        else:
            logger.warning(
                "No supervised model artifacts were loaded. "
                "Expected at least one of: %s, %s",
                settings.ml_nsl_model_path,
                settings.ml_loghub_model_path,
            )

    def _load_ensemble_config(self) -> None:
        config_path_raw = str(settings.ml_ensemble_config_path).strip()
        if not config_path_raw:
            return

        config_path = self._resolve_artifact_path(config_path_raw)
        if not config_path.exists():
            return

        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse ensemble config %s: %s", config_path, exc)
            return

        weights = payload.get("weights", {}) if isinstance(payload, dict) else {}
        thresholds = payload.get("thresholds", {}) if isinstance(payload, dict) else {}

        if isinstance(weights, dict):
            self._weights["nsl"] = self._safe_float(weights.get("nsl"), self._weights["nsl"])
            self._weights["loghub"] = self._safe_float(weights.get("loghub"), self._weights["loghub"])

        if isinstance(thresholds, dict):
            self._thresholds["nsl"] = self._safe_float(
                thresholds.get("nsl"), self._thresholds["nsl"]
            )
            self._thresholds["loghub"] = self._safe_float(
                thresholds.get("loghub"), self._thresholds["loghub"]
            )
            self._thresholds["ensemble"] = self._safe_float(
                thresholds.get("ensemble"), self._thresholds["ensemble"]
            )

        logger.info(
            "Loaded ensemble config from %s (weights=%s thresholds=%s)",
            config_path,
            self._weights,
            self._thresholds,
        )

    def _safe_load_model(self, model_path_raw: str, label: str) -> Any:
        model_path = self._resolve_artifact_path(model_path_raw)
        if not model_path.exists():
            logger.warning("Model artifact not found for %s: %s", label, model_path)
            return None

        try:
            model = joblib.load(model_path)
            logger.info("Loaded %s model from %s", label, model_path)
            return model
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            logger.warning("Failed loading %s model from %s: %s", label, model_path, exc)
            return None

    def _resolve_artifact_path(self, configured_path: str) -> Path:
        path = Path(configured_path).expanduser()
        if path.is_absolute():
            return path
        return (self._base_dir / path).resolve()

    def _predict_nsl_attack_prob(
        self,
        events: List[Dict[str, Any]],
        feature_vector: np.ndarray,
    ) -> Optional[float]:
        if self._nsl_pipeline is None or pd is None:
            return None

        row = self._build_nsl_feature_row(events, feature_vector)
        sample_df = pd.DataFrame([row], columns=NSL_KDD_FEATURE_COLUMNS)

        if hasattr(self._nsl_pipeline, "predict_proba"):
            probs = self._nsl_pipeline.predict_proba(sample_df)
            if len(probs.shape) == 2 and probs.shape[1] > 1:
                return self._clip_probability(float(probs[0][1]))
            return self._clip_probability(float(probs[0][0]))

        pred = self._nsl_pipeline.predict(sample_df)
        return self._clip_probability(float(np.asarray(pred).reshape(-1)[0]))

    def _predict_loghub_attack_prob(self, events: List[Dict[str, Any]]) -> Optional[float]:
        if self._loghub_pipeline is None:
            return None

        samples = self._build_loghub_samples(events)
        if not samples:
            return 0.0

        if hasattr(self._loghub_pipeline, "predict_proba"):
            probs = np.asarray(self._loghub_pipeline.predict_proba(samples), dtype=float)
            if probs.ndim == 2 and probs.shape[1] > 1:
                scores = probs[:, 1]
            else:
                scores = probs.reshape(-1)
            return self._clip_probability(float(np.mean(scores)))

        pred = np.asarray(self._loghub_pipeline.predict(samples), dtype=float).reshape(-1)
        return self._clip_probability(float(np.mean(pred)))

    def _combine_scores(
        self,
        nsl_prob: Optional[float],
        loghub_prob: Optional[float],
    ) -> float:
        weighted_sum = 0.0
        total_weight = 0.0

        if nsl_prob is not None:
            w = max(0.0, self._weights["nsl"])
            weighted_sum += w * nsl_prob
            total_weight += w

        if loghub_prob is not None:
            w = max(0.0, self._weights["loghub"])
            weighted_sum += w * loghub_prob
            total_weight += w

        if total_weight <= 0:
            values = [v for v in (nsl_prob, loghub_prob) if v is not None]
            return float(np.mean(values)) if values else 0.0

        return weighted_sum / total_weight

    def _build_loghub_samples(self, events: List[Dict[str, Any]]) -> List[str]:
        samples: List[str] = []

        for ev in events[:120]:
            data = self._parse_event_data(ev)
            event_type = str(ev.get("event_type", "UNKNOWN")).upper()
            package_name = str(ev.get("package_name", "") or data.get("package", "")).strip()

            tokens = [event_type]
            if package_name:
                tokens.append(f"pkg={package_name}")

            for key in (
                "permission",
                "domain",
                "url",
                "host",
                "action",
                "uid",
                "rxBytesDelta",
                "txBytesDelta",
                "dstPort",
                "dstHost",
                "riskScore",
                "category",
                "isSideLoaded",
            ):
                value = data.get(key)
                if value is None:
                    continue
                value_str = str(value).strip()
                if not value_str:
                    continue
                tokens.append(f"{key}={value_str}")

            samples.append(" ".join(tokens))

        return samples

    def _build_nsl_feature_row(
        self,
        events: List[Dict[str, Any]],
        feature_vector: np.ndarray,
    ) -> Dict[str, Any]:
        event_count = float(max(len(events), 1))
        network_events = 0.0
        security_events = 0.0
        auth_failures = 0.0
        auth_successes = 0.0
        file_accesses = 0.0
        file_creations = 0.0
        src_bytes = 0.0
        dst_bytes = 0.0
        package_names: set[str] = set()

        for ev in events:
            event_type = str(ev.get("event_type", "")).upper()
            data = self._parse_event_data(ev)

            package_candidate = ev.get("package_name") or data.get("package") or data.get("packageName")
            if isinstance(package_candidate, str) and package_candidate.strip():
                package_names.add(package_candidate.strip().lower())

            if event_type in {"NETWORK_TRAFFIC", "NETWORK_APP", "NETWORK_FLOW"}:
                network_events += 1
                rx = self._safe_float(data.get("rxBytesDelta", data.get("rxBytes", 0.0)), 0.0)
                tx = self._safe_float(data.get("txBytesDelta", data.get("txBytes", 0.0)), 0.0)
                src_bytes += max(0.0, tx)
                dst_bytes += max(0.0, rx)

                flow_bytes = self._safe_float(data.get("bytes"), 0.0)
                if flow_bytes > 0:
                    src_bytes += flow_bytes * 0.5
                    dst_bytes += flow_bytes * 0.5

            if event_type in {
                "SECURITY_PACKAGE_EVENT",
                "SECURITY_AUTH_EVENT",
                "PERMISSION_ACCESS",
                "CANARY_FILE_ACCESS",
                "WEB_DOMAIN",
            }:
                security_events += 1

            if event_type == "SECURITY_AUTH_EVENT":
                status = str(data.get("status", "")).strip().lower()
                success_raw = data.get("success")
                is_success = self._safe_bool(success_raw, default=status in {"ok", "success", "passed"})
                if is_success:
                    auth_successes += 1
                else:
                    auth_failures += 1

            if event_type == "CANARY_FILE_ACCESS" or "file" in event_type.lower():
                file_accesses += 1
                action = str(data.get("action", "")).upper()
                if action in {"CREATE", "WRITE", "SAVE"}:
                    file_creations += 1

        unique_packages = float(len(package_names))
        service = self._guess_service(events)
        protocol = self._guess_protocol(events)
        flag = "REJ" if auth_failures > 0 else "SF"

        duration_seconds = self._event_window_span(events)
        if duration_seconds <= 0 and feature_vector.size > 0:
            duration_seconds = min(300.0, float(np.linalg.norm(feature_vector) * 3.0))

        serror_rate = self._ratio(security_events, event_count)
        rerror_rate = self._ratio(auth_failures, event_count)
        same_srv_rate = self._ratio(network_events, event_count)
        diff_srv_rate = max(0.0, 1.0 - same_srv_rate)
        srv_count_denom = max(network_events, 1.0)

        return {
            "duration": round(duration_seconds, 4),
            "protocol_type": protocol,
            "service": service,
            "flag": flag,
            "src_bytes": round(src_bytes, 4),
            "dst_bytes": round(dst_bytes, 4),
            "land": 0.0,
            "wrong_fragment": 0.0,
            "urgent": 0.0,
            "hot": float(security_events),
            "num_failed_logins": float(auth_failures),
            "logged_in": 1.0 if auth_successes > 0 else 0.0,
            "num_compromised": float(file_accesses),
            "root_shell": 0.0,
            "su_attempted": 0.0,
            "num_root": 0.0,
            "num_file_creations": float(file_creations),
            "num_shells": 0.0,
            "num_access_files": float(file_accesses),
            "num_outbound_cmds": 0.0,
            "is_host_login": 0.0,
            "is_guest_login": 0.0,
            "count": event_count,
            "srv_count": float(network_events),
            "serror_rate": serror_rate,
            "srv_serror_rate": self._ratio(security_events, srv_count_denom),
            "rerror_rate": rerror_rate,
            "srv_rerror_rate": self._ratio(auth_failures, srv_count_denom),
            "same_srv_rate": same_srv_rate,
            "diff_srv_rate": diff_srv_rate,
            "srv_diff_host_rate": self._ratio(unique_packages, srv_count_denom),
            "dst_host_count": unique_packages,
            "dst_host_srv_count": float(network_events),
            "dst_host_same_srv_rate": same_srv_rate,
            "dst_host_diff_srv_rate": diff_srv_rate,
            "dst_host_same_src_port_rate": self._ratio(network_events, network_events + security_events),
            "dst_host_srv_diff_host_rate": self._ratio(unique_packages, event_count),
            "dst_host_serror_rate": serror_rate,
            "dst_host_srv_serror_rate": serror_rate,
            "dst_host_rerror_rate": rerror_rate,
            "dst_host_srv_rerror_rate": rerror_rate,
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

    def _guess_protocol(self, events: List[Dict[str, Any]]) -> str:
        for ev in events:
            data = self._parse_event_data(ev)
            for key in ("protocol", "proto", "transport", "networkType"):
                value = data.get(key)
                if not isinstance(value, str):
                    continue
                text = value.strip().lower()
                if text.startswith("tcp"):
                    return "tcp"
                if text.startswith("udp"):
                    return "udp"
                if text.startswith("icmp"):
                    return "icmp"
        return "tcp"

    def _guess_service(self, events: List[Dict[str, Any]]) -> str:
        saw_web_domain = False
        saw_permission = False
        saw_dns_port = False
        saw_http_port = False

        for ev in events:
            event_type = str(ev.get("event_type", "")).upper()
            data = self._parse_event_data(ev)

            if event_type == "WEB_DOMAIN":
                saw_web_domain = True
            if event_type in {"PERMISSION_ACCESS", "SECURITY_PACKAGE_EVENT", "CANARY_FILE_ACCESS"}:
                saw_permission = True

            for port_key in ("dstPort", "port", "remotePort"):
                port_val = data.get(port_key)
                port = int(self._safe_float(port_val, -1.0))
                if port == 53:
                    saw_dns_port = True
                if port in (80, 443, 8080):
                    saw_http_port = True

        if saw_web_domain or saw_http_port:
            return "http"
        if saw_dns_port:
            return "domain_u"
        if saw_permission:
            return "private"
        return "other"

    @staticmethod
    def _event_window_span(events: List[Dict[str, Any]]) -> float:
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
            return 0.0

        return max(0.0, max(timestamps) - min(timestamps))

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "ok", "success", "passed"}:
                return True
            if normalized in {"0", "false", "no", "n", "fail", "failed", "error"}:
                return False
        return default

    @staticmethod
    def _ratio(numerator: float, denominator: float) -> float:
        if denominator <= 0:
            return 0.0
        return float(min(max(numerator / denominator, 0.0), 1.0))

    @staticmethod
    def _clip_probability(value: float) -> float:
        return float(min(max(value, 0.0), 1.0))
