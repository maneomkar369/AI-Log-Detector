# Android App Description for Behavioral Anomaly Detection System

## App Overview

The Behavioral Anomaly Detector is an Android application that continuously monitors user behavior patterns (app usage, typing rhythm, touch interactions) and detects anomalies that may indicate security threats such as device misuse, malware, or unauthorized access. It communicates with a low-power edge server (Raspberry Pi) via secure WebSocket (NGROK tunnel) to offload heavy processing while preserving privacy.

## Core Features

- Background Monitoring: Runs as a foreground service to collect behavioral data with low battery impact.
- Usage Statistics: Tracks app usage timing and duration via `UsageStatsManager`.
- Keystroke & Touch Tracking: Uses `AccessibilityService` with explicit user consent.
- Local Storage: Buffers events in Room and retries sync when offline.
- Real-time Alerting: Receives anomaly alerts via WebSocket.
- User Approval Workflow: Lets the user approve/deny neutralization actions.
- Settings & Permissions: Guides Usage Stats, Accessibility, and Notifications setup.

## Architecture (MVVM + Clean)

- UI Layer: `MainActivity`, settings/alerts screens, adapters
- ViewModel Layer: `MainViewModel` exposing LiveData/Flow
- Domain Layer: Collect, send, execute, process use-cases
- Data Layer: Room, WebSocket manager, settings store
- Services Layer: Foreground collector + accessibility service

## Key Components

### 1) Behavioral Data Collection

- `UsageStatsCollector`: periodic foreground app usage sampling
- Accessibility events: text changed + clicked events
- Buffered sync: Room `synced` flag and periodic flush worker

### 2) Communication

- `WebSocketManager`: `wss://<ngrok-url>/ws/<device_id>`
- Automatic reconnect: exponential backoff
- Alert stream: exposed for ViewModel/UI rendering

### 3) Local Database (Room)

- `BehaviorEvent`: id, timestamp, type, packageName, data, synced, retryCount
- `Alert`: id, anomalyId, timestamp, severity, threatType, message, status

### 4) User Interface

- Main status: connection, last sync, recent alerts
- Alert cards by severity
- Approval dialog: Approve / Deny / Snooze

### 5) Permissions Handling

- Usage Stats settings redirect
- Accessibility service enablement flow
- Notifications runtime permission (Android 13+)
- Battery optimization exemption prompt

## Technology Stack

- Language: Kotlin
- Min SDK: API 26
- Architecture: MVVM + Clean Architecture
- DI: Dagger Hilt
- Database: Room + DataStore
- Networking: OkHttp WebSocket, Retrofit (optional)
- Async: Coroutines + Flow
- Background: WorkManager + Foreground Service
- JSON: Gson

## Workflow Summary

1. App requests permissions.
2. Foreground service collects behavioral data.
3. Data buffered locally and sent via WebSocket.
4. Edge server performs anomaly detection.
5. Alerts return to app and are displayed to user.
6. User approves/denies neutralization actions.
7. Audit records are kept locally and on edge.

## Deliverables

- Functional Android APK
- Cleanly structured source code with documentation
- Sample edge server connection configuration
