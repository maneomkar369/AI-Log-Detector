# Behavioral Anomaly Detection - Task List

Source: CONTEXT.md (analyzed on 2026-04-02)

## NOW (Immediate Execution)

- [ ] Raspberry Pi hardware assembled and powered
- [ ] Raspberry Pi OS installed and configured
- [ ] Static IP address configured
- [ ] SSH enabled for remote access
- [ ] Firewall configured (ports 22, 8000, 5000, 5432, 6379)
- [ ] Update OS packages (`apt update && apt upgrade`)
- [ ] Install required packages (Python, PostgreSQL, Redis, Nginx, Git)
- [ ] Create project directory structure (`backend`, `dashboard`, `models`, `logs`)
- [ ] Create and activate Python virtual environment
- [ ] Install Python dependencies for edge server
- [ ] Initialize PostgreSQL database and user
- [ ] Configure and start Redis service
- [ ] Configure environment variables in `.env`
- [ ] Configure NGROK auth token and tunnel
- [ ] Create and enable systemd services (`anomaly-detection`, `ngrok`)

## NEXT (Core Build & Validation)

- [x] Complete Permissions & Security implementation (starter scaffold)
- [x] Complete Database Design implementation (Room entities/DAO/database scaffold)
- [x] Complete Services Implementation (collector + accessibility service scaffold)
- [x] Complete UI/UX Design implementation (MainActivity + basic status UI scaffold)
- [x] Complete Edge Server Integration (WebSocketManager + repository scaffold)
- [ ] Build Android release APK
- [ ] Sign APK
- [ ] Align APK
- [ ] Install APK on test device
- [ ] Implement and run unit tests:
  - [ ] test_normal_behavior
  - [ ] test_sudden_anomaly
- [ ] Set up monitoring (Prometheus/Grafana optional)

### Build Notes

- Android project scaffold has been created under `android/`.
- Remaining unchecked items require local Android SDK/keystore/device execution.

## LATER (Enhancements / Roadmap)

- [ ] Federated Learning (Q3 2026)
- [ ] Biometric Integration (Q4 2026)
- [ ] Cloud Backup (Q1 2027)
- [ ] Plugin System (Q2 2027)
- [ ] iOS Support (Q3 2027)
- [ ] Multi-device Correlation (Q4 2027)

## OPEN ITEMS / PENDING DETAILS

- [ ] Add concrete model download commands (placeholder exists in setup script)
- [ ] Replace placeholder secrets and credentials with secure values
- [ ] Confirm production domain for NGROK configuration
- [ ] Confirm alert channel credentials (FCM, Twilio, Email)
