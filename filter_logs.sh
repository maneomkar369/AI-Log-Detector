#!/bin/bash

# Filter Logcat to show only relevant AI Log Detector messages
# Excludes SELinux denials and other system noise.

echo "--- Starting Clean Log Stream for AI Log Detector ---"
echo "Filtering for: MonitoringService, WebSocketClient, PermissionMonitor, AlertManager"

adb logcat -v time \
    MonitoringService:I \
    WebSocketClient:I \
    PermissionMonitor:I \
    AlertManager:I \
    AnomalousEvent:D \
    SecurityEvent:D \
    *:S | grep -v "avc: denied" | grep -v "auditd" | grep -v "bpf"
