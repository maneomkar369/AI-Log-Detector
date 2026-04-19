# Edge Server Setup on Raspberry Pi

This guide is focused on edge_server deployment on Raspberry Pi.
It uses the current default stack in this repo:

- FastAPI edge server
- SQLite database (default)
- Redis buffer/pubsub

Optional sections are included for ngrok and systemd autostart.

## Project values used in this workspace

- Repository URL: https://github.com/maneomkar369/AI-Log-Detector.git
- Current ngrok domain in Android config: grid-scuff-diploma.ngrok-free.dev

## 1. Recommended hardware/software

- Raspberry Pi 4 (4GB+) or Pi 5
- Raspberry Pi OS 64-bit (Bookworm)
- Stable internet connection

## 2. Install system packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  git curl redis-server \
  python3 python3-venv python3-pip python3-dev \
  build-essential gfortran libopenblas-dev liblapack-dev
```

Notes:

- The math build packages are included for reliable numpy/scipy install on ARM.
- If pip finds wheels, install is faster.

## 3. Clone project and install edge_server deps

```bash
cd ~
git clone https://github.com/maneomkar369/AI-Log-Detector.git AI-Log-Detector
cd AI-Log-Detector/edge_server

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

## 4. Configure environment

Create a repo-level .env file:

```bash
cd ~/AI-Log-Detector
cp .env.example .env
nano .env
```

Minimum values to set:

```env
DATABASE_URL=sqlite+aiosqlite:///./anomaly_detection.db
REDIS_URL=redis://localhost:6379/0
EDGE_SERVER_HOST=0.0.0.0
EDGE_SERVER_PORT=8000
```

## 5. Start Redis and run the edge server

```bash
sudo systemctl enable redis-server
sudo systemctl restart redis-server

cd ~/AI-Log-Detector/edge_server
source .venv/bin/activate
python main.py
```

Verify from another terminal:

```bash
curl -sS http://127.0.0.1:8000/api/health && echo
```

If you can see status ok, edge server is running.

## 6. Optional: run as a systemd service

Create /etc/systemd/system/anomaly-detection.service:

```ini
[Unit]
Description=Behavioral Anomaly Detection Edge Server
After=network.target redis-server.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/AI-Log-Detector/edge_server
Environment="PATH=/home/pi/AI-Log-Detector/edge_server/.venv/bin"
ExecStart=/home/pi/AI-Log-Detector/edge_server/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable/start service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable anomaly-detection
sudo systemctl start anomaly-detection
sudo systemctl status anomaly-detection
```

## 7. Optional: expose edge server with ngrok

Install ngrok (arm64):

```bash
cd /tmp
curl -LO https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz
sudo tar -xzf ngrok-v3-stable-linux-arm64.tgz -C /usr/local/bin
ngrok version
```

Authenticate and run tunnel:

```bash
ngrok config add-authtoken YOUR_NGROK_TOKEN
ngrok http 8000
```

If using reserved domain:

```bash
ngrok http --domain=grid-scuff-diploma.ngrok-free.dev 8000
```

Android app should use:

```text
wss://grid-scuff-diploma.ngrok-free.dev/ws
```

## 8. Optional: autostart ngrok with systemd

Create /etc/systemd/system/ngrok.service:

```ini
[Unit]
Description=ngrok tunnel for anomaly detector
After=network.target

[Service]
Type=simple
User=pi
ExecStart=/usr/local/bin/ngrok http --domain=grid-scuff-diploma.ngrok-free.dev 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable/start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ngrok
sudo systemctl start ngrok
sudo systemctl status ngrok
```

## 9. Ready copy-paste sequence (project-specific)

Use this block on Raspberry Pi to set up edge server + ngrok autostart with this project's real values.

```bash
PI_USER=pi
PROJECT_DIR=/home/$PI_USER/AI-Log-Detector

sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  git curl redis-server \
  python3 python3-venv python3-pip python3-dev \
  build-essential gfortran libopenblas-dev liblapack-dev

if [ ! -d "$PROJECT_DIR/.git" ]; then
  git clone https://github.com/maneomkar369/AI-Log-Detector.git "$PROJECT_DIR"
fi

cd "$PROJECT_DIR/edge_server"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
pip install -r requirements.txt

cd "$PROJECT_DIR"
cp -n .env.example .env
sed -i 's|^DATABASE_URL=.*|DATABASE_URL=sqlite+aiosqlite:///./anomaly_detection.db|' .env
sed -i 's|^REDIS_URL=.*|REDIS_URL=redis://localhost:6379/0|' .env
sed -i 's|^EDGE_SERVER_HOST=.*|EDGE_SERVER_HOST=0.0.0.0|' .env
sed -i 's|^EDGE_SERVER_PORT=.*|EDGE_SERVER_PORT=8000|' .env

sudo systemctl enable redis-server
sudo systemctl restart redis-server

sudo tee /etc/systemd/system/anomaly-detection.service >/dev/null <<EOF
[Unit]
Description=Behavioral Anomaly Detection Edge Server
After=network.target redis-server.service

[Service]
Type=simple
User=$PI_USER
WorkingDirectory=$PROJECT_DIR/edge_server
Environment="PATH=$PROJECT_DIR/edge_server/.venv/bin"
ExecStart=$PROJECT_DIR/edge_server/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cd /tmp
curl -LO https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz
sudo tar -xzf ngrok-v3-stable-linux-arm64.tgz -C /usr/local/bin
ngrok config add-authtoken YOUR_NGROK_TOKEN

sudo tee /etc/systemd/system/ngrok.service >/dev/null <<EOF
[Unit]
Description=ngrok tunnel for anomaly detector
After=network.target anomaly-detection.service

[Service]
Type=simple
User=$PI_USER
ExecStart=/usr/local/bin/ngrok http --domain=grid-scuff-diploma.ngrok-free.dev 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable anomaly-detection ngrok
sudo systemctl restart anomaly-detection ngrok

curl -sS http://127.0.0.1:8000/api/health && echo
sudo systemctl status anomaly-detection --no-pager
sudo systemctl status ngrok --no-pager
```

## 10. Troubleshooting

pip install fails on scipy/numpy:

- Ensure you installed build dependencies from step 2.
- Upgrade pip and wheel before pip install -r requirements.txt.

Port 8000 already in use:

- Stop old process/service using port 8000, then restart edge server.

Android cannot connect:

- Ensure app URL is wss://.../ws.
- Ensure ngrok is running and domain is active.
- Ensure the Raspberry Pi firewall/router allows outbound traffic.