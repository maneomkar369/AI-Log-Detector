# Simple Full-Stack Setup Guide

This guide runs the complete stack on one machine:

- Edge server (FastAPI)
- Dashboard (Flask + Socket.IO)
- PostgreSQL
- Redis
- Android app connected through ngrok

For Raspberry Pi edge deployment, see [EDGE_SERVER_RASPBERRY_PI_SETUP.md](EDGE_SERVER_RASPBERRY_PI_SETUP.md).

## Project values used in this workspace

- Repository URL: https://github.com/maneomkar369/AI-Log-Detector.git
- Current ngrok domain in Android config: grid-scuff-diploma.ngrok-free.dev

If your ngrok domain changes, update SERVER_URL in [android/app/src/main/java/com/anomalydetector/Config.kt](android/app/src/main/java/com/anomalydetector/Config.kt).

## 1. Prerequisites

- Docker with Compose support
- Android Studio (for the Android app)
- JDK 17 for Android Gradle builds (Java 25 is not supported by this project tooling)
- ngrok account + ngrok CLI
- Git

## 2. Start the full stack

From the project root:

```bash
docker compose up -d --build
docker compose ps
```

Expected local services:

- Edge server: http://127.0.0.1:8000
- Dashboard: http://127.0.0.1:5000

Quick health checks:

```bash
curl -sS http://127.0.0.1:8000/api/health && echo
curl -sS http://127.0.0.1:5000/api/dashboard/alerts && echo
```

## 3. Expose the edge server with ngrok

```bash
ngrok config add-authtoken YOUR_NGROK_TOKEN
ngrok http 8000
```

If you use a reserved domain:

```bash
ngrok http --domain=grid-scuff-diploma.ngrok-free.dev 8000
```

Take the HTTPS host and build Android WebSocket URL as:

```text
wss://grid-scuff-diploma.ngrok-free.dev/ws
```

## 4. Configure the Android app

Update SERVER_URL in [android/app/src/main/java/com/anomalydetector/Config.kt](android/app/src/main/java/com/anomalydetector/Config.kt):

```kotlin
var SERVER_URL = "wss://grid-scuff-diploma.ngrok-free.dev/ws"
```

Then in Android Studio:

1. Open the [android](android) folder.
2. Sync Gradle.
3. Run the app on your device/emulator.
4. Grant required permissions: Usage Access, Accessibility, Notifications.

## 5. Android log coverage (what is sent)

The app now sends these log categories to the server:

- App behavior logs: APP_USAGE, KEYSTROKE, TOUCH, SWIPE
- Network traffic logs: NETWORK_TRAFFIC (device-level deltas), NETWORK_APP (per-app UID deltas)
- VPN flow logs (optional): NETWORK_FLOW, NETWORK_FLOW_STATUS
- Security/auth logs: SECURITY_AUTH_EVENT (screen/auth state), SECURITY_PACKAGE_EVENT (install/update/remove)
- System logs/state: SYSTEM_STATE (memory + battery), SYSTEM_LOGCAT_ACCESS (whether logcat is accessible)

VPN flow capture mode:

- The app includes a VPN flow monitor service and permission flow in UI.
- Safe mode is default (no TUN interception) to avoid breaking device connectivity.
- To enable raw TUN mode without forwarding (not recommended), set:
  - ENABLE_VPN_TUN_CAPTURE=true
  - ENABLE_VPN_CAPTURE_WITHOUT_FORWARDING=true
- To enable forwarding mode (recommended for connectivity), set:
  - ENABLE_VPN_TUN_CAPTURE=true
  - ENABLE_VPN_FORWARDER=true
  - VPN_FORWARDER_COMMAND to a working tun2socks-style command on device.

Example forwarder command:

```text
/data/local/tmp/tun2socks --tunfd %TUN_FD% --netif-ipaddr 10.42.0.2 --netif-netmask 255.255.255.0 --socks-server-addr 127.0.0.1:1080
```

Android platform limits:

- Full device logcat is restricted on non-root consumer devices.
- Deep packet inspection/network payload capture requires VPNService or root tooling.
- Detailed auth failure logs are limited unless running as device owner/system app.

Backend rule alerts now also trigger on high-risk windows, even if pure model distance is not extreme:

- package modification bursts (SECURITY_PACKAGE_EVENT)
- abnormal auth/screen churn (SECURITY_AUTH_EVENT)
- high network burst with low-memory or critical-battery system stress

## 6. Verify end-to-end flow

Use one of these test methods.

Method A (real app):

1. Tap Start Monitoring in the Android app.
2. Use the phone for a few minutes.
3. Check backend stats/alerts with your device ID.

Method B (simulator script):

```bash
cd tests/load
python3 -m venv .venv
source .venv/bin/activate
pip install websockets
python simulate_devices.py --devices 1 --duration 90 --server ws://127.0.0.1:8000/ws
```

Check data:

```bash
curl -sS http://127.0.0.1:8000/api/stats/YOUR_DEVICE_ID && echo
curl -sS "http://127.0.0.1:8000/api/alerts/YOUR_DEVICE_ID?limit=5" && echo
```

## 7. Stop services

```bash
docker compose down
```

If you want to also remove volumes:

```bash
docker compose down -v
```

## 8. Common issues

Port already in use:

- Stop old local processes using port 8000/5000, then restart compose.

Android shows Disconnected:

- Verify SERVER_URL uses wss:// and ends with /ws.
- Verify ngrok tunnel is still running.

Dashboard has no live updates:

- Verify Redis container is healthy with docker compose ps.

Android Gradle build fails with java.lang.IllegalArgumentException: 25.0.2:

- Run Gradle with Java 17.
- Example command:

```bash
JAVA_HOME=$(/usr/libexec/java_home -v 17) ./gradlew :app:compileDebugKotlin
```
