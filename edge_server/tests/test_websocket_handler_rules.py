"""
Tests for WebSocket rule-based alert logic.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.websocket_handler import ConnectionManager
from config import settings
from services.anomaly_detector import AnomalyResult, ThreatType


def test_rule_alert_none_for_normal_window():
    events = [
        {
            "event_type": "APP_USAGE",
            "package_name": "com.chrome",
            "timestamp": 1700000000000,
            "data": "{}",
        },
        {
            "event_type": "TOUCH",
            "timestamp": 1700000001000,
            "data": '{"duration": 120}',
        },
    ]

    assert ConnectionManager._evaluate_rule_alert(events) is None


def test_rule_alert_for_package_modification_burst():
    events = [
        {
            "event_type": "SECURITY_PACKAGE_EVENT",
            "timestamp": 1700000000000,
            "data": '{"action": "android.intent.action.PACKAGE_ADDED"}',
        },
        {
            "event_type": "SECURITY_PACKAGE_EVENT",
            "timestamp": 1700000000100,
            "data": '{"action": "android.intent.action.PACKAGE_REPLACED"}',
        },
    ]

    alert = ConnectionManager._evaluate_rule_alert(events)
    assert alert is not None
    assert alert["threat_type"] == "INSIDER_THREAT"
    assert alert["severity"] >= 7


def test_rule_alert_for_network_stress_pattern():
    events = [
        {
            "event_type": "SYSTEM_STATE",
            "timestamp": 1700000000000,
            "data": '{"lowMemory": true, "batteryPct": 8}',
        },
        {
            "event_type": "NETWORK_TRAFFIC",
            "timestamp": 1700000000100,
            # ~26 MB burst
            "data": '{"rxBytesDelta": 20971520, "txBytesDelta": 6291456}',
        },
    ]

    alert = ConnectionManager._evaluate_rule_alert(events)
    assert alert is not None
    assert alert["threat_type"] == "DEVICE_MISUSE"
    assert alert["severity"] == 8


def test_rule_prefers_higher_severity_candidate():
    events = [
        # Package burst triggers severity >= 7
        {
            "event_type": "SECURITY_PACKAGE_EVENT",
            "timestamp": 1700000000000,
            "data": '{"action": "android.intent.action.PACKAGE_ADDED"}',
        },
        {
            "event_type": "SECURITY_PACKAGE_EVENT",
            "timestamp": 1700000000100,
            "data": '{"action": "android.intent.action.PACKAGE_REPLACED"}',
        },
        # Network stress should push to severity 8
        {
            "event_type": "SYSTEM_STATE",
            "timestamp": 1700000000200,
            "data": '{"lowMemory": true, "batteryPct": 7}',
        },
        {
            "event_type": "NETWORK_TRAFFIC",
            "timestamp": 1700000000300,
            "data": '{"rxBytesDelta": 26214400, "txBytesDelta": 4194304}',
        },
    ]

    alert = ConnectionManager._evaluate_rule_alert(events)
    assert alert is not None
    assert alert["severity"] == 8
    assert alert["threat_type"] == "DEVICE_MISUSE"


def test_rule_alert_for_known_malicious_app(monkeypatch):
    monkeypatch.setattr(settings, "malicious_apps", "com.bad.malware,com.fakebanker.app")
    monkeypatch.setattr(settings, "ignored_alert_packages", "")

    events = [
        {
            "event_type": "APP_USAGE",
            "package_name": "com.bad.malware",
            "timestamp": 1700000000000,
            "data": "{}",
        }
    ]

    alert = ConnectionManager._evaluate_rule_alert(events)
    assert alert is not None
    assert alert["threat_type"] == "MALWARE_MIMICRY"
    assert alert["severity"] == 9
    assert alert["indicator"] == "app:com.bad.malware"


def test_rule_alert_for_known_malicious_domain(monkeypatch):
    monkeypatch.setattr(settings, "malicious_domains", "phishing.test,evil.test")

    events = [
        {
            "event_type": "WEB_DOMAIN",
            "package_name": "com.android.chrome",
            "timestamp": 1700000000000,
            "data": '{"domain": "login.phishing.test"}',
        }
    ]

    alert = ConnectionManager._evaluate_rule_alert(events)
    assert alert is not None
    assert alert["threat_type"] == "MALWARE_MIMICRY"
    assert alert["severity"] == 8
    assert alert["indicator"] == "domain:login.phishing.test"


def test_rule_alert_none_for_benign_domain(monkeypatch):
    monkeypatch.setattr(settings, "malicious_domains", "phishing.test,evil.test")

    events = [
        {
            "event_type": "WEB_DOMAIN",
            "package_name": "com.android.chrome",
            "timestamp": 1700000000000,
            "data": '{"domain": "example.com"}',
        }
    ]

    assert ConnectionManager._evaluate_rule_alert(events) is None


def test_rule_alert_ignored_package_suppresses_ioc(monkeypatch):
    monkeypatch.setattr(settings, "malicious_apps", "com.bad.malware")
    monkeypatch.setattr(settings, "ignored_alert_packages", "com.bad.malware")

    events = [
        {
            "event_type": "APP_USAGE",
            "package_name": "com.bad.malware",
            "timestamp": 1700000000000,
            "data": "{}",
        }
    ]

    assert ConnectionManager._evaluate_rule_alert(events) is None


def test_ignored_device_matching(monkeypatch):
    monkeypatch.setattr(settings, "ignored_alert_device_ids", "ioc_test_device")
    monkeypatch.setattr(settings, "ignored_alert_device_prefixes", "test_device_,ioc_test_")

    assert ConnectionManager._is_ignored_device("ioc_test_device")
    assert ConnectionManager._is_ignored_device("test_device_0001")
    assert ConnectionManager._is_ignored_device("ioc_test_abc")
    assert not ConnectionManager._is_ignored_device("f9ed08dc27055482")


def test_xai_explanation_includes_indicator_for_rule_alert():
    events = [
        {
            "event_type": "APP_USAGE",
            "package_name": "com.bad.malware",
            "timestamp": 1700000000000,
            "data": "{}",
        },
        {
            "event_type": "SECURITY_PACKAGE_EVENT",
            "timestamp": 1700000000500,
            "data": '{"action":"android.intent.action.PACKAGE_REPLACED"}',
        },
    ]
    rule_alert = {
        "severity": 9,
        "threat_type": "MALWARE_MIMICRY",
        "message": "Known malicious app activity detected: com.bad.malware",
        "confidence": 0.97,
        "indicator": "app:com.bad.malware",
    }

    explanation = ConnectionManager._build_xai_explanation(
        events=events,
        detection=None,
        rule_alert=rule_alert,
        alert_source="rule",
        selected_threat_type="MALWARE_MIMICRY",
        selected_severity=9,
        selected_message=rule_alert["message"],
        selected_confidence=0.97,
        selected_distance=0.0,
        selected_threshold=None,
    )

    assert explanation["version"] == "xai-v1"
    assert explanation["rule"]["indicator"] == "app:com.bad.malware"
    assert "MALWARE_MIMICRY" in explanation["summary"]


def test_xai_explanation_includes_model_ratio_for_anomaly():
    events = [
        {
            "event_type": "APP_USAGE",
            "package_name": "com.example.safe",
            "timestamp": 1700000000000,
            "data": "{}",
        },
        {
            "event_type": "APP_USAGE",
            "package_name": "com.example.safe",
            "timestamp": 1700000001300,
            "data": "{}",
        },
    ]

    detection = AnomalyResult(
        is_anomaly=True,
        mahalanobis_distance=18.0,
        threshold=6.0,
        severity=8,
        confidence=0.91,
        threat_type=ThreatType.DEVICE_MISUSE,
        message="Sudden behavioral deviation detected",
    )

    explanation = ConnectionManager._build_xai_explanation(
        events=events,
        detection=detection,
        rule_alert=None,
        alert_source="model",
        selected_threat_type="DEVICE_MISUSE",
        selected_severity=8,
        selected_message=detection.message,
        selected_confidence=0.91,
        selected_distance=18.0,
        selected_threshold=6.0,
    )

    assert explanation["model"]["distance_ratio"] == 3.0
    assert explanation["window"]["event_count"] == 2
    assert explanation["source"] == "model"
