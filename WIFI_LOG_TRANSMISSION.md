# BAD (Behavioral Log Anomaly Detector) - WiFi Log Transmission

## Overview

The BAD Android app now includes comprehensive WiFi connectivity management to ensure secure and efficient log transmission to the server.

## Features Implemented

### 1. WiFi Connectivity Monitoring
- **Real-time WiFi Status**: Continuously monitors device WiFi connection status
- **Network Type Detection**: Identifies current network type (WiFi, Cellular, Ethernet)
- **Fallback Handling**: Gracefully handles network unavailability with event buffering

### 2. Enhanced Log Transmission
The app collects behavioral logs and sends them to the edge server through multiple channels:

**Event Types Transmitted:**
- **APP_USAGE**: Real app foreground time statistics
- **NETWORK_TRAFFIC**: Device-wide network traffic (RX/TX bytes)
- **NETWORK_APP**: Per-application network usage with UID tracking
- **SECURITY_PACKAGE_EVENT**: Package install/uninstall events
- **SECURITY_AUTH_EVENT**: Screen on/off, user present events
- **SYSTEM_STATE**: Memory, battery, system metrics
- **SYSTEM_LOGCAT_ACCESS**: Logcat permission probing results

### 3. WiFi-First Policy
The app implements a WiFi-first transmission policy:

```
IF WiFi Connected:
  ✅ Send logs immediately via WebSocket
  
ELSE IF Network Connected (Cellular/Ethernet):
  ⚠️ Send with warning log
  Buffer for WiFi retry
  
ELSE:
  ❌ Buffer events locally
  Wait for network + WiFi
  Send when available
```

### 4. Network Permissions
Added permissions to AndroidManifest.xml:

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
<uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
<uses-permission android:name="android.permission.READ_LOGS" />
```

---

## Architecture

### WiFiConnectivityMonitor (New Component)

Located: `android/app/src/main/java/com/anomalydetector/service/WiFiConnectivityMonitor.kt`

**Key Methods:**
- `isWiFiConnected(context: Context): Boolean` - Check WiFi status
- `isNetworkConnected(context: Context): Boolean` - Check any network
- `getNetworkTypeName(context: Context): String` - Get network type name
- `logNetworkStatus(context: Context)` - Log current network status

### MonitoringService (Updated Component)

Enhanced with:
- WiFi connectivity checks before syncing events
- Network type logging on startup
- Warnings when using non-WiFi networks
- Event buffering when no network available

**Updated syncEvents() Method:**
```kotlin
suspend fun syncEvents() {
  1. Check WiFi connectivity
  2. Verify network available
  3. Warn if using cellular
  4. Send events via WebSocket
  5. Mark events as synced
}
```

### WebSocketClient (Existing Component)

Unchanged but utilized by enhanced MonitoringService:
- Connects to edge server: `wss://[server]/ws/{device_id}`
- Sends batched behavioral events as JSON
- Receives alerts and approval messages
- Auto-reconnects on failure

---

## Data Flow

```
Device Sensors
    ↓
MonitoringService collects events
    ↓
Check WiFi Status
    ├─ WiFi: Send immediately
    ├─ Cellular: Send with warning
    └─ None: Buffer locally
    ↓
WebSocketClient
    ↓
Edge Server (ws://localhost:8000/ws/{device_id})
    ↓
Anomaly Detection
    ↓
Dashboard + Alerts
```

---

## Log Output Examples

### Startup (WiFi Connected)
```
[WiFiMonitor] Network Status - WiFi: true | Connected: true | Type: WiFi
[MonitoringService] WebSocket connected
[MonitoringService] ✓ Synced 12 events via WiFi
```

### Startup (Cellular Only)
```
[WiFiMonitor] Network Status - WiFi: false | Connected: true | Type: Cellular
[MonitoringService] Warning: Using Cellular instead of WiFi for data transmission (may incur charges)
[MonitoringService] ✓ Synced 12 events via Cellular
```

### No Network
```
[WiFiMonitor] Network Status - WiFi: false | Connected: false | Type: Unknown
[MonitoringService] No network connection available. Events buffered for later sync.
```

---

## Configuration

### App Name
- **Display Name**: BAD
- **Full Name**: Behavioral Log Anomaly Detector
- **Package ID**: com.bad

### Transmission Settings

Edit `Config.kt` to customize:

```kotlin
var SERVER_URL = "wss://grid-scuff-diploma.ngrok-free.dev/ws"
var SAMPLING_INTERVAL_MS = 10_000L      // 10 seconds
var RECONNECT_DELAY_MS = 5_000L         // 5 seconds
const val EVENT_BATCH_SIZE = 50         // Events per sync
```

---

## Server Integration

### Edge Server Endpoints

The app connects via WebSocket to:
```
ws://[edge_server]:8000/ws/{device_id}
```

**Expected Server Responses:**
1. `onOpen()` - Connection established
2. `alert` messages - Anomaly alerts with actions
3. `approval` requests - User approval/denial

### Event Payload Format

Each event transmitted includes:
```json
{
  "type": "APP_USAGE",
  "packageName": "com.example.app",
  "timestamp": 1713174000000,
  "data": "{\"totalTime\": 5000, \"lastUsed\": \"2026-04-15T...\"}"
}
```

---

## Testing WiFi Transmission

### Test Scenario 1: WiFi Connected
```bash
1. Connect device to WiFi network
2. Start BAD app
3. Check logcat: "Network Status - WiFi: true"
4. Verify events synced via WebSocket
```

### Test Scenario 2: Cellular Only
```bash
1. Disable WiFi, enable Cellular
2. Start BAD app
3. Check logcat: "Warning: Using Cellular"
4. Verify events still sent (with warning)
```

### Test Scenario 3: No Network
```bash
1. Enable Airplane Mode
2. Start BAD app
3. Check logcat: "No network connection"
4. Disable Airplane Mode
5. Verify events sync when network returns
```

---

## Performance Metrics

- **Event Collection**: Every 10 seconds
- **Batch Size**: 50 events per sync
- **WebSocket Ping**: Every 30 seconds
- **Reconnect Delay**: 5 seconds
- **Network Check**: Per sync (negligible overhead)

---

## Security Considerations

✅ **Implemented:**
- iOS/Android native network modules (no custom networking)
- WebSocket over HTTPS (wss://)
- Device ID-based identification
- Event-level timestamps for audit trail
- Protected permissions for system API access

⚠️ **To Consider:**
- Certificate pinning for production
- Data encryption in transit
- VPN compatibility testing
- Network bandwidth optimization

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Events not syncing | No WiFi | Check device WiFi connection |
| Connection refused | Server down | Verify edge server running |
| Certificate error | SSL issue | Update device time/certificates |
| Events delayed | Buffering | Wait for WiFi + reconnection |
| High data usage | Cellular fallback | Enable WiFi or optimize batch size |

---

## Next Steps

1. **Build the App**
   ```bash
   cd android
   ./gradlew clean build
   ```

2. **Install on Device**
   ```bash
   ./gradlew installDebug
   ```

3. **Monitor Logs**
   ```bash
   adb logcat | grep -E "BAD|WiFiMonitor|WebSocket"
   ```

4. **Verify Server Reception**
   ```bash
   # Check edge server logs
   docker compose logs -f edge_server | grep "Device connected"
   ```

---

**BAD is now ready to transmit behavioral logs via WiFi to the anomaly detection server!** 📲
