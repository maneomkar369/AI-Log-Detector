"""
Test Server — Minimal Mock for Quick Testing
==============================================
A standalone FastAPI server with mock anomaly detection.
Use this for the 30-minute Quick Start test before full deployment.

Run:
    python test_server.py
"""

import json
import random
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_server")

# ── In-memory state ──
connected_devices = {}
alert_history = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🧪 Test server starting (mock anomaly detection)")
    yield
    logger.info("Test server stopped")


app = FastAPI(title="Anomaly Detector — Test Server", lifespan=lifespan)


@app.get("/")
async def root():
    return {
        "service": "Test Server (Mock)",
        "devices_connected": len(connected_devices),
        "alerts_generated": len(alert_history),
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": "test"}


@app.get("/api/alerts/{device_id}")
async def get_alerts(device_id: str):
    return [a for a in alert_history if a["device_id"] == device_id]


@app.post("/api/alerts/{alert_id}/approve")
async def approve(alert_id: str):
    for a in alert_history:
        if a["anomaly_id"] == alert_id:
            a["status"] = "approved"
            return {"status": "approved", "anomalyId": alert_id}
    return {"error": "not found"}


@app.post("/api/alerts/{alert_id}/deny")
async def deny(alert_id: str):
    for a in alert_history:
        if a["anomaly_id"] == alert_id:
            a["status"] = "denied"
            return {"status": "denied", "anomalyId": alert_id}
    return {"error": "not found"}


@app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    await websocket.accept()
    connected_devices[device_id] = websocket
    logger.info("✅ Device connected: %s", device_id)

    try:
        while True:
            data = await websocket.receive_text()
            events = json.loads(data)
            if not isinstance(events, list):
                events = [events]

            logger.info("📥 %s sent %d events", device_id, len(events))

            # Simple anomaly heuristic: >10 events in one batch = suspicious
            if len(events) > 10:
                severity = min(10, len(events) - 5)
                alert = {
                    "type": "alert",
                    "anomaly_id": f"alt_test_{random.randint(1000,9999)}",
                    "device_id": device_id,
                    "severity": severity,
                    "threatType": "DEVICE_MISUSE",
                    "message": f"{len(events)} events in a single burst",
                    "confidence": round(random.uniform(0.7, 0.99), 2),
                    "actions": ["kill_process", "block_network"],
                    "status": "pending",
                    "timestamp": datetime.utcnow().isoformat(),
                }
                alert_history.append(alert)

                # Send alert to device
                await websocket.send_text(json.dumps({
                    k: v for k, v in alert.items()
                    if k != "device_id"
                }))
                logger.warning("🚨 ALERT sent to %s: severity=%d", device_id, severity)
            else:
                await websocket.send_text(json.dumps({
                    "type": "ack",
                    "eventsReceived": len(events),
                }))

    except WebSocketDisconnect:
        connected_devices.pop(device_id, None)
        logger.info("❌ Device disconnected: %s", device_id)


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  🧪 BEHAVIORAL ANOMALY DETECTOR — TEST SERVER")
    print("=" * 60)
    print("  WebSocket : ws://localhost:8000/ws/{device_id}")
    print("  REST API  : http://localhost:8000/api/")
    print("  Docs      : http://localhost:8000/docs")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
