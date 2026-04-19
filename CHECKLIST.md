# 5-Minute Team Onboarding Checklist

## First-time setup

- [ ] Clone repo and open project root.
- [ ] Install Docker Desktop and ngrok CLI.
- [ ] Run: `ngrok config add-authtoken YOUR_TOKEN`
- [ ] Connect Android device with USB debugging enabled.

## Start system

- [ ] Run: `./scripts/start_all.sh`
- [ ] If using reserved domain: `NGROK_DOMAIN=your-domain.ngrok-free.dev ./scripts/start_all.sh`
- [ ] Open dashboard: http://localhost:5001
- [ ] Confirm edge health: http://localhost:8000/api/health

## Android app

- [ ] Set SERVER_URL in android/app/src/main/java/com/anomalydetector/Config.kt to: `wss://YOUR_DOMAIN/ws`
- [ ] Build and install app from Android Studio.
- [ ] Grant Usage Access, Accessibility, and Notifications permissions.
- [ ] Tap Start Monitoring and confirm status is Live.

## End of day

- [ ] Run: `./scripts/stop_all.sh`
- [ ] Optional cleanup: `CLEAN_VOLUMES=1 ./scripts/stop_all.sh`
