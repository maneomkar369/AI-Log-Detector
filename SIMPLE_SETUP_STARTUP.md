# Simple Setup And Startup Guide

This is a practical, copy-paste guide to run the full AI-Log-Detector system.

What you get:
- Edge server (FastAPI + WebSocket)
- Dashboard (Flask + Socket.IO)
- PostgreSQL + Redis
- Android app connected through ngrok

## 1. Prerequisites

- Docker Desktop (or Docker Engine + Compose)
- Android Studio (for Android app)
- ADB device with USB debugging enabled
- ngrok account + ngrok CLI installed
- Git

## 2. Clone Project

```bash
git clone https://github.com/maneomkar369/AI-Log-Detector.git
cd AI-Log-Detector
```

## 3. Start Backend Stack (One Command)

From project root:

```bash
docker compose up -d --build
```

Check status:

```bash
docker compose ps
```

Expected ports:
- Edge server: http://localhost:8000
- Dashboard: http://localhost:5001
- Postgres: localhost:5433
- Redis: localhost:6379

## 4. Health Check

```bash
curl -sS http://localhost:8000/api/health && echo
curl -sS http://localhost:5001/api/dashboard/alerts && echo
```

If these return JSON, backend is ready.

## 5. Start ngrok For Android Connectivity

First time only:

```bash
ngrok config add-authtoken YOUR_NGROK_TOKEN
```

Run tunnel:

```bash
ngrok http 8000
```

Or with reserved domain:

```bash
ngrok http --domain=grid-scuff-diploma.ngrok-free.dev 8000
```

WebSocket URL format for Android:

```text
wss://YOUR_NGROK_DOMAIN/ws
```

## 6. Configure Android App

Open file:
- android/app/src/main/java/com/anomalydetector/Config.kt

Set:

```kotlin
var SERVER_URL = "wss://YOUR_NGROK_DOMAIN/ws"
```

Then in Android Studio:
1. Open android folder.
2. Sync Gradle.
3. Install app on phone.
4. Grant permissions: Usage Access, Accessibility, Notifications.

## 7. Daily Startup Order (Simple)

Every time you want to run the system:

1. Start Docker stack

```bash
cd AI-Log-Detector
docker compose up -d
```

2. Start ngrok

```bash
ngrok http 8000
```

3. Verify Android URL still matches current ngrok domain
- Config.kt -> SERVER_URL

4. Open app and tap Start Monitoring

5. Open dashboard in browser
- http://localhost:5001

## 8. Quick Verify End-to-End

- App header status should show Live.
- Dashboard should show incoming events/alerts.
- API check with your device id:

```bash
curl -sS "http://localhost:8000/api/alerts/YOUR_DEVICE_ID?limit=5" && echo
```

## 9. Stop Everything

Stop stack:

```bash
docker compose down
```

Stop and remove volumes too (optional cleanup):

```bash
docker compose down -v
```

Stop ngrok with Ctrl+C in ngrok terminal.

## 10. Common Fixes

Android stuck on Disconnected:
- Ensure URL is wss://.../ws (must include /ws).
- Ensure ngrok is still running.
- Ensure backend is up: docker compose ps

Dashboard not opening:
- Use http://localhost:5001 (not 5000 in compose mode).

No events visible:
- Confirm permissions granted in app.
- Confirm Monitoring started in app.
- Confirm edge health endpoint responds.

ADB-related actions not working from containers:
- Start local adb server first:

```bash
adb start-server
adb devices
```

## 11. Optional: Run Without Docker (Dev Mode)

Edge server:

```bash
cd edge_server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Dashboard:

```bash
cd dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Note: In non-docker mode, defaults are usually:
- Edge: 8000
- Dashboard: 5000

---

If you want, I can also generate a one-page START.sh + STOP.sh so your team can run the full stack with two commands.
