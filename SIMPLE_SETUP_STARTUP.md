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

If dashboard logs show:

```text
failed to connect to 'host.docker.internal:5037': network is unreachable
```

Use host-IP bridge mode instead of host.docker.internal:

```bash
# 1) Start host adb server
adb start-server
adb devices

# 2) In project root .env
ADB_SERVER_SOCKET=tcp:YOUR_HOST_LAN_IP:5037

# 3) Restart stack
docker compose up -d --build
```

Dashboard browser CSP warning about eval:
- The dashboard now sends explicit CSP headers and avoids inline scripts.
- If a third-party script still requires string evaluation in your environment, set:

```bash
DASHBOARD_CSP_ALLOW_UNSAFE_EVAL=true
```

Only enable this as a temporary compatibility fallback.

## 11. Real Alert Mode (No Fake/Test Alerts)

Use this profile when you want production-like alerts only.

1. Keep IOC lists empty unless you add verified real indicators in .env:

```bash
MALICIOUS_APPS=
MALICIOUS_DOMAINS=
RULE_ALERT_COOLDOWN_SECONDS=120
IGNORED_ALERT_DEVICE_IDS=ioc_test_device
IGNORED_ALERT_DEVICE_PREFIXES=test_device_,ioc_test_
IGNORED_ALERT_PACKAGES=com.bad.malware
```

2. Remove the dummy test app from device (if installed):

```bash
adb uninstall com.bad.malware
```

3. Restart backend services:

```bash
docker compose up -d --build edge_server
docker compose restart dashboard
```

4. Remove historical fake/test data (one-time cleanup):

```bash
docker compose exec postgres psql -U admin -d anomaly_detection -c "BEGIN; \
DELETE FROM alerts \
WHERE device_id='ioc_test_device' \
	OR device_id LIKE 'test_device_%' \
	OR lower(message) LIKE '%com.bad.malware%' \
	OR lower(coalesce(actions,'')) LIKE '%com.bad.malware%' \
	OR lower(message) LIKE '%dummy%'; \
DELETE FROM behavior_events \
WHERE device_id='ioc_test_device' \
	OR device_id LIKE 'test_device_%' \
	OR lower(coalesce(package_name,''))='com.bad.malware'; \
COMMIT;"
```

5. Verify fake indicators are gone:

```bash
docker compose exec postgres psql -U admin -d anomaly_detection -c "SELECT COUNT(*) AS alerts_dummy_or_temp FROM alerts WHERE device_id='ioc_test_device' OR device_id LIKE 'test_device_%' OR lower(message) LIKE '%com.bad.malware%' OR lower(coalesce(actions,'')) LIKE '%com.bad.malware%' OR lower(message) LIKE '%dummy%';"
docker compose exec postgres psql -U admin -d anomaly_detection -c "SELECT COUNT(*) AS events_dummy_or_temp FROM behavior_events WHERE device_id='ioc_test_device' OR device_id LIKE 'test_device_%' OR lower(coalesce(package_name,''))='com.bad.malware';"
curl -sS http://localhost:5001/api/dashboard/alerts | grep -i -E 'com.bad.malware|ioc_test_device|test_device_' || echo "No fake alert matches in dashboard API"
```

## 12. Optional: Run Without Docker (Dev Mode)

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
Status:

Ran 
./scripts/start_all.sh 
from start_all.sh
Docker services are Up: dashboard, edge_server, postgres, redis
Edge health OK: {"status":"ok","service":"behavioral-anomaly-detector"}
Dashboard API OK: returned [] for alerts (no alerts yet)
ngrok active URL: https://grid-scuff-diploma.ngrok-free.dev (forwarding to localhost:8000)
Use this in Android config:

Config.kt
Set SERVER_URL to: wss://grid-scuff-diploma.ngrok-free.dev/ws
When done, stop with:

./scripts/stop_all.sh