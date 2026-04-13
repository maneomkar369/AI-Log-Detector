# Setup Guide

This guide helps you run the Behavioral Log Anomaly Detector in three modes:

- Option A: Quick local demo (mock server, fastest)
- Option B: Full local stack with Docker Compose (recommended for full features)
- Option C: Manual full stack (without Docker)

## 1. Prerequisites

## System

- Linux, macOS, or WSL2
- Python 3.10+
- Git
- Android Studio (for Android app)
- ngrok account (for remote Android to local server)

## Optional tools

- Node.js + npm (for `wscat` WebSocket testing)
- Docker + Docker Compose (for full stack)
- PostgreSQL + Redis (manual full stack)

## Project root

```bash
cd /home/vishal/jarvis/New-AI_log
```

---

## 2. Option A - Quick Test on PC (about 30 minutes)

Use this when you want the fastest end-to-end demo.

### Step A1 - Start Edge Test Server (mock mode)

```bash
cd /home/vishal/jarvis/New-AI_log/edge_server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python test_server.py
```

Expected startup banner:

```text
============================================================
  BEHAVIORAL ANOMALY DETECTOR - TEST SERVER
============================================================
  WebSocket : ws://localhost:8000/ws/{device_id}
  REST API  : http://localhost:8000/api/
  Docs      : http://localhost:8000/docs
============================================================
```

Open docs:

- http://localhost:8000/docs

### Step A2 - Expose local server via ngrok (for Android)

```bash
ngrok authtoken YOUR_AUTH_TOKEN
ngrok http 8000
```

Copy your forwarding URL, for example:

- https://abc123.ngrok-free.app

### Step A3 - Android app setup

1. Open Android Studio.
2. Open folder: `/home/vishal/jarvis/New-AI_log/android`.
3. Wait for Gradle sync.
4. Edit `app/src/main/java/com/anomalydetector/Config.kt`:

```kotlin
var SERVER_URL = "wss://abc123.ngrok-free.app/ws"
```

5. Connect Android phone (USB debugging enabled).
6. Run the app.

### Step A4 - Grant Android permissions

Grant all required permissions on the phone:

- Usage Access
- Accessibility Service
- Notifications

### Step A5 - Trigger a mock anomaly

Install wscat (one time):

```bash
npm i -g wscat
```

Connect:

```bash
wscat -c ws://localhost:8000/ws/test_device_001
```

Generate a payload with 12 events (mock server alerts on more than 10 events in one batch):

```bash
python3 -c "import json,time;print(json.dumps([{'type':'APP_USAGE','packageName':f'com.test{i}','timestamp':int(time.time()*1000)+i,'data':'{}'} for i in range(12)]))"
```

Paste that JSON into the open wscat session and press Enter.

## Important notes for Option A

- The dashboard can run, but live streaming requires Redis channel publishing.
- The mock server is for quick testing and does not represent full production behavior.

---

## 3. Option B - Full Local Stack with Docker Compose (recommended)

Use this mode when you need full pipeline behavior:

- PostgreSQL persistence
- Redis buffering and pub/sub
- Real anomaly pipeline
- Dashboard + edge server together

### Step B1 - Prepare environment file

```bash
cd /home/vishal/jarvis/New-AI_log
cp .env.example .env
nano .env
```

Set at least these values:

```env
DATABASE_URL=postgresql+asyncpg://admin:your_password@localhost:5432/anomaly_detection
REDIS_URL=redis://localhost:6379/0
NGROK_AUTH_TOKEN=your_ngrok_token
DASHBOARD_SECRET_KEY=replace-with-a-random-secret
```

### Step B2 - Start services

```bash
docker-compose up -d
```

Services:

- Edge server: http://localhost:8000
- Dashboard: http://localhost:5000
- PostgreSQL: localhost:5432
- Redis: localhost:6379

### Step B3 - Verify health

```bash
curl http://localhost:8000/api/health
curl http://localhost:5000/api/dashboard/alerts
docker-compose ps
```

### Step B4 - Connect Android app

If Android is on another network/device, expose edge server:

```bash
ngrok authtoken YOUR_AUTH_TOKEN
ngrok http 8000
```

Then update Android `SERVER_URL` with your ngrok WSS URL ending in `/ws`.

## Important notes for Option B

- Dashboard approve/deny buttons call `/api/alerts/...`.
- For those buttons to work from dashboard UI, you need reverse proxy routing (`/api` -> edge server), or you must call edge API directly on port 8000.

---

## 4. Option C - Manual Full Setup (without Docker)

Use this if you prefer running each service directly.

### Step C1 - Install system dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv postgresql redis-server nginx git
```

### Step C2 - Configure PostgreSQL

```bash
sudo -u postgres psql << EOF
CREATE DATABASE anomaly_detection;
CREATE USER admin WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE anomaly_detection TO admin;
\q
EOF
```

### Step C3 - Start Redis

```bash
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

### Step C4 - Run edge server

```bash
cd /home/vishal/jarvis/New-AI_log/edge_server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Step C5 - Run dashboard

Open a second terminal:

```bash
cd /home/vishal/jarvis/New-AI_log/dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

---

## 5. Optional Production-Style Services (systemd)

```bash
cd /home/vishal/jarvis/New-AI_log
sudo cp deploy/anomaly-detection.service /etc/systemd/system/
sudo cp deploy/ngrok.service /etc/systemd/system/

# Edit service files to match your machine paths/domain
sudo nano /etc/systemd/system/anomaly-detection.service
sudo nano /etc/systemd/system/ngrok.service

sudo systemctl daemon-reload
sudo systemctl enable anomaly-detection ngrok
sudo systemctl start anomaly-detection ngrok
```

Check status:

```bash
sudo systemctl status anomaly-detection
sudo systemctl status ngrok
```

---

## 6. Optional Nginx Reverse Proxy

```bash
cd /home/vishal/jarvis/New-AI_log
sudo cp deploy/nginx.conf /etc/nginx/sites-available/anomaly-detector
sudo ln -s /etc/nginx/sites-available/anomaly-detector /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

This is useful to:

- Serve dashboard and API under one domain
- Route `/ws` and `/api` to edge server
- Enable dashboard action buttons without custom frontend changes

---

## 7. Pipeline Testing

### Health check

```bash
curl http://localhost:8000/api/health
```

### WebSocket test client

```bash
wscat -c ws://localhost:8000/ws/test_device_001
```

### Mock mode payload (test_server.py)

Use more than 10 events in one batch to trigger alert.

### Full edge mode payload (main.py)

The Redis batch analyzer processes windows of 50 events, so send at least 50 events for quick detection cycles.

---

## 8. Troubleshooting

### Dashboard shows no live events

- Ensure Redis is running.
- Ensure you are using full edge server mode (not only mock test server).

### Dashboard approve/deny returns 404

- You are likely opening dashboard directly on port 5000 without reverse proxy.
- Use Nginx routing for `/api` to edge server, or call edge API directly on port 8000.

### Android build fails with missing drawable `card_bg`

- Check `activity_main.xml` references.
- Add the missing drawable resource or replace the background reference.

### ngrok URL works in browser but Android cannot connect

- Use `wss://.../ws` format in `Config.kt`.
- Confirm your phone has internet access.
- Regenerate URL if ngrok session expired.

### Edge server starts but ingestion fails

- Verify Redis connection URL.
- Verify PostgreSQL credentials if running full mode.

---

## 9. Suggested First Validation Sequence

1. Run Option A and confirm Android connects.
2. Trigger mock alert with a large batch.
3. Move to Option B for full Redis/PostgreSQL workflow.
4. Add Nginx routing when testing dashboard actions end-to-end.
