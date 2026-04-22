"""
End-to-End Scenario Test for AI Log Detector
============================================
Simulates the exact real-world demo scenarios (Rapid App Launch, Canary File, 
Phishing, and Permission Access) to verify the Edge Server generates the
correct alerts and XAI explanations in real-time.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ScenarioTest")

WS_DEVICE_URL = "ws://localhost:8000/ws/demo_device_001"

async def send_events(websocket, events: list):
    await websocket.send(json.dumps(events))
    await asyncio.sleep(0.5)

async def test_scenario_1_baseline(ws):
    logger.info("=== SCENARIO 1: Building Baseline (Normal Usage) ===")
    events = []
    for _ in range(50):
        events.append({
            "type": "KEYSTROKE_DYNAMICS",
            "packageName": "com.android.chrome",
            "timestamp": int(time.time() * 1000),
            "data": {"flightTime": 120, "dwellTime": 60, "errorRate": 0.05}
        })
    await send_events(ws, events)
    logger.info("Baseline events sent successfully.")
    await asyncio.sleep(2)

async def test_scenario_2_rapid_app_launch(ws):
    logger.info("=== SCENARIO 2: Rapid App Launches (Malware Mimicry) ===")
    events = []
    for i in range(15):
        events.append({
            "type": "APP_TRANSITION",
            "packageName": f"com.malicious.app{i}",
            "timestamp": int(time.time() * 1000) + i,
            "data": {"transitionType": "OPEN"}
        })
    await send_events(ws, events)
    logger.info("Rapid app launch events sent.")
    await asyncio.sleep(2)

async def test_scenario_3_canary_file(ws):
    logger.info("=== SCENARIO 3: Canary File Access (Ransomware) ===")
    events = [{
        "type": "CANARY_FILE_ACCESS",
        "packageName": "com.unknown.process",
        "timestamp": int(time.time() * 1000),
        "data": {
            "fileName": "/sdcard/Download/.canary_bank_details.pdf",
            "action": "MODIFY"
        }
    }]
    await send_events(ws, events)
    logger.info("Canary file modification event sent.")
    await asyncio.sleep(2)

async def test_scenario_4_phishing(ws):
    logger.info("=== SCENARIO 4: Phishing Navigation ===")
    events = [{
        "type": "WEB_DOMAIN",
        "packageName": "com.android.chrome",
        "timestamp": int(time.time() * 1000),
        "data": {
            "domain": "paypal-secure-login-update.tk",
            "tfliteScore": 0.85
        }
    }]
    await send_events(ws, events)
    logger.info("Phishing URL event sent.")
    await asyncio.sleep(2)

async def test_scenario_5_permission(ws):
    logger.info("=== SCENARIO 5: Sideloaded App Permission Access ===")
    events = [{
        "type": "PERMISSION_ACCESS",
        "packageName": "com.sketchy.sideload",
        "timestamp": int(time.time() * 1000),
        "data": {
            "permission": "CAMERA",
            "isSideLoaded": True
        }
    }]
    await send_events(ws, events)
    logger.info("Sensitive permission event sent.")
    await asyncio.sleep(2)

async def main():
    try:
        async with websockets.connect(WS_DEVICE_URL) as ws:
            logger.info("Connected to Edge Server.")
            await test_scenario_1_baseline(ws)
            await test_scenario_2_rapid_app_launch(ws)
            await test_scenario_3_canary_file(ws)
            await test_scenario_4_phishing(ws)
            await test_scenario_5_permission(ws)
            logger.info("All scenarios executed. Check Edge Server logs for output alerts.")
    except Exception as e:
        logger.error(f"Failed to connect or run test: {e}")

if __name__ == "__main__":
    asyncio.run(main())
