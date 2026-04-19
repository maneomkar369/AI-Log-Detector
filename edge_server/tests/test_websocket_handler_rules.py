"""
Tests for WebSocket rule-based alert logic.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.websocket_handler import ConnectionManager


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
