#!/usr/bin/env python3
"""
Pre-Demo Checklist Verifier for AI Log Detector
===============================================
Runs automated checks on the host machine to verify Demo Day readiness.
Checks ADB connections, Docker status, File artifacts, and MacOS applications.
"""

import os
import subprocess
import json
import urllib.request
import logging

def print_result(item: str, passed: bool, details: str = ""):
    icon = "✅" if passed else "❌"
    print(f"{icon} {item.ljust(50)} {details}")
    return passed

def run_cmd(cmd: str) -> str:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except:
        return ""

print("\n🚀 AI Log Detector - Pre-Demo Flight Check 🚀\n" + "="*55)

# 1. Preparation
print("\n[ Preparation ]")
has_trigger = os.path.exists("trigger_demo.sh")
print_result("Test anomaly scripts prepared", has_trigger, "(trigger_demo.sh)")

has_apk = os.path.exists("DummySuspiciousApp.apk")
print_result("Malicious test APK available", has_apk, "(DummySuspiciousApp.apk)")

# Check Postgres baseline (needs docker)
baseline_passed = False
try:
    pg_out = run_cmd('/usr/local/bin/docker exec ai-log-detector-postgres-1 psql -U admin -d anomaly_detection -t -c "SELECT MAX(baseline_sample_count) FROM devices;"')
    max_baseline = int(pg_out.strip() or 0)
    baseline_passed = max_baseline > 50
    print_result("Behavioral baseline built", baseline_passed, f"(Max baseline: {max_baseline} events)")
except:
    print_result("Behavioral baseline built", False, "(Failed to query database)")

# 2. Connections
print("\n[ Connections ]")
adb_devices = run_cmd('/Users/vishal/Library/Android/sdk/platform-tools/adb devices')
connected_devices = [line for line in adb_devices.split('\n') if 'device' in line and 'List' not in line]
has_device = len(connected_devices) > 0
print_result("ADB Over Wi-Fi / USB connected", has_device, f"(Found {len(connected_devices)} devices)")

edge_up = False
try:
    req = urllib.request.urlopen("http://localhost:8000/api/health", timeout=2)
    edge_up = req.getcode() == 200
except:
    pass
print_result("Edge Server running & accessible", edge_up, "(Port 8000)")

dash_up = False
try:
    req = urllib.request.urlopen("http://localhost:5001", timeout=2)
    dash_up = req.getcode() == 200
except:
    pass
print_result("Dashboard running & accessible", dash_up, "(Port 5001)")

# Look for active websocket in logs
ws_active = False
logs = run_cmd('/usr/local/bin/docker logs ai-log-detector-edge_server-1 | tail -n 50')
if "connection open" in logs or "accepted" in logs:
    ws_active = True
print_result("WebSocket connection established", ws_active, "(Server log check)")


# 3. Screen Capture Tools (MacOS)
print("\n[ Screen Capture ]")
has_scrcpy = "scrcpy" in run_cmd("which scrcpy") or os.path.exists("/opt/homebrew/bin/scrcpy")
print_result("scrcpy Installed", has_scrcpy)

has_obs = os.path.exists("/Applications/OBS.app")
print_result("OBS Studio Installed", has_obs)


# 4. Fallback Materials
print("\n[ Fallback Packages ]")
fallback_dir = "fallback_materials"
if not os.path.exists(fallback_dir):
    os.makedirs(fallback_dir)

# Dump server logs to fallback
run_cmd(f'/usr/local/bin/docker logs ai-log-detector-edge_server-1 > {fallback_dir}/successful_run_server.log')
has_logs = os.path.exists(f"{fallback_dir}/successful_run_server.log")
print_result("Log files accessible", has_logs, "(fallback_materials/)")
print_result("Screenshots & Backup Videos", False, "(Action Required: Record using OBS)")

print("\n=======================================================")
if has_device and edge_up and dash_up:
    print("✅ SYSTEM IS READY FOR DEMO (Software & Network Passed)")
else:
    print("⚠️  ACTION REQUIRED: Address the red 'X' items above before demo.")
print("=======================================================\n")
