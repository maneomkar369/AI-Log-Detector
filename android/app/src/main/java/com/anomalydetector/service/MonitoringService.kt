package com.anomalydetector.service

import android.app.*
import android.app.usage.UsageStats
import android.app.usage.UsageStatsManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.TrafficStats
import android.os.BatteryManager
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.anomalydetector.Config
import com.anomalydetector.data.local.AppDatabase
import com.anomalydetector.data.model.BehaviorEvent
import com.anomalydetector.data.remote.WebSocketClient
import com.anomalydetector.ui.MainActivity
import com.google.gson.Gson
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import javax.inject.Inject

/**
 * Foreground service that collects app usage statistics
 * and sends them to the edge server via WebSocket.
 */
@AndroidEntryPoint
class MonitoringService : Service() {

    @Inject lateinit var database: AppDatabase

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var webSocketClient: WebSocketClient? = null
    private val gson = Gson()
    private val uidTrafficBaseline = mutableMapOf<Int, Pair<Long, Long>>()
    private var totalRxBaseline = -1L
    private var totalTxBaseline = -1L
    private var receiversRegistered = false

    private val authReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                Intent.ACTION_USER_PRESENT -> {
                    persistSecurityEvent(
                        eventType = "SECURITY_AUTH_EVENT",
                        payload = mapOf("event" to "USER_PRESENT")
                    )
                }
                Intent.ACTION_SCREEN_ON -> {
                    persistSecurityEvent(
                        eventType = "SECURITY_AUTH_EVENT",
                        payload = mapOf("event" to "SCREEN_ON")
                    )
                }
                Intent.ACTION_SCREEN_OFF -> {
                    persistSecurityEvent(
                        eventType = "SECURITY_AUTH_EVENT",
                        payload = mapOf("event" to "SCREEN_OFF")
                    )
                }
            }
        }
    }

    private val packageReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            val action = intent?.action ?: return
            val packageName = intent.data?.schemeSpecificPart

            when (action) {
                Intent.ACTION_PACKAGE_ADDED,
                Intent.ACTION_PACKAGE_REMOVED,
                Intent.ACTION_PACKAGE_REPLACED -> {
                    persistSecurityEvent(
                        eventType = "SECURITY_PACKAGE_EVENT",
                        packageName = packageName,
                        payload = mapOf(
                            "action" to action,
                            "replacing" to intent.getBooleanExtra(Intent.EXTRA_REPLACING, false)
                        )
                    )
                }
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        setMonitoringEnabled(this, true)
        registerSecurityReceivers()
        createNotificationChannels()
        startForeground(Config.NOTIFICATION_MONITORING, buildNotification())
        updateConnectionStatus("Connecting...")
        startMonitoring()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Keep monitoring alive and let the system restart the service if needed.
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        scope.cancel()
        webSocketClient?.disconnect()
        unregisterSecurityReceivers()
        updateConnectionStatus("Disconnected")
        super.onDestroy()
    }

    private fun startMonitoring() {
        // Log network connectivity status
        WiFiConnectivityMonitor.logNetworkStatus(this)
        
        // Connect WebSocket
        val deviceId = android.provider.Settings.Secure.getString(
            contentResolver, android.provider.Settings.Secure.ANDROID_ID
        )
        webSocketClient = WebSocketClient(deviceId, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "WebSocket connected")
                updateConnectionStatus("Connected")
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleServerMessage(text)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket error: ${t.message}")
                updateConnectionStatus("Disconnected")
                // Auto-reconnect after delay
                scope.launch {
                    delay(Config.RECONNECT_DELAY_MS)
                    updateConnectionStatus("Reconnecting...")
                    webSocketClient?.connect()
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                updateConnectionStatus("Disconnected")
            }
        })
        updateConnectionStatus("Connecting...")
        webSocketClient?.connect()

        scope.launch {
            probeLogcatAccess()
        }

        // Collect and sync logs periodically
        scope.launch {
            while (isActive) {
                val usageStats = collectUsageStats()
                collectNetworkStats(usageStats)
                collectSystemSnapshot()
                syncEvents()
                delay(Config.SAMPLING_INTERVAL_MS)
            }
        }
    }

    private suspend fun collectUsageStats(): List<UsageStats> {
        try {
            val usm = getSystemService(Context.USAGE_STATS_SERVICE) as? UsageStatsManager
                ?: return emptyList()

            val endTime = System.currentTimeMillis()
            val startTime = endTime - Config.SAMPLING_INTERVAL_MS

            val stats = usm.queryUsageStats(
                UsageStatsManager.INTERVAL_BEST, startTime, endTime
            ) ?: emptyList()

            stats.filter { it.totalTimeInForeground > 0 }.forEach { stat ->
                val event = BehaviorEvent(
                    eventType = "APP_USAGE",
                    packageName = stat.packageName,
                    timestamp = endTime,
                    data = gson.toJson(mapOf(
                        "totalTime" to stat.totalTimeInForeground,
                        "lastUsed" to stat.lastTimeUsed
                    ))
                )
                database.behaviorEventDao().insert(event)
            }
            return stats
        } catch (e: Exception) {
            Log.e(TAG, "Failed to collect usage stats: ${e.message}")
            return emptyList()
        }
    }

    private suspend fun collectNetworkStats(usageStats: List<UsageStats>) {
        try {
            val now = System.currentTimeMillis()
            val unsupported = TrafficStats.UNSUPPORTED.toLong()

            val totalRx = TrafficStats.getTotalRxBytes()
            val totalTx = TrafficStats.getTotalTxBytes()
            if (totalRx != unsupported && totalTx != unsupported) {
                if (totalRxBaseline >= 0 && totalTxBaseline >= 0) {
                    val rxDelta = (totalRx - totalRxBaseline).coerceAtLeast(0)
                    val txDelta = (totalTx - totalTxBaseline).coerceAtLeast(0)
                    if (rxDelta > 0 || txDelta > 0) {
                        database.behaviorEventDao().insert(
                            BehaviorEvent(
                                eventType = "NETWORK_TRAFFIC",
                                timestamp = now,
                                data = gson.toJson(
                                    mapOf(
                                        "rxBytesDelta" to rxDelta,
                                        "txBytesDelta" to txDelta,
                                        "intervalMs" to Config.SAMPLING_INTERVAL_MS
                                    )
                                )
                            )
                        )
                    }
                }
                totalRxBaseline = totalRx
                totalTxBaseline = totalTx
            }

            val activePackages = usageStats
                .asSequence()
                .filter { it.totalTimeInForeground > 0 }
                .map { it.packageName }
                .toSet()

            activePackages.forEach { packageName ->
                val uid = try {
                    packageManager.getApplicationInfo(packageName, 0).uid
                } catch (_: PackageManager.NameNotFoundException) {
                    return@forEach
                }

                val uidRx = TrafficStats.getUidRxBytes(uid)
                val uidTx = TrafficStats.getUidTxBytes(uid)
                if (uidRx == unsupported || uidTx == unsupported) {
                    return@forEach
                }

                val previous = uidTrafficBaseline[uid]
                uidTrafficBaseline[uid] = uidRx to uidTx
                if (previous == null) {
                    return@forEach
                }

                val rxDelta = (uidRx - previous.first).coerceAtLeast(0)
                val txDelta = (uidTx - previous.second).coerceAtLeast(0)
                if (rxDelta == 0L && txDelta == 0L) {
                    return@forEach
                }

                database.behaviorEventDao().insert(
                    BehaviorEvent(
                        eventType = "NETWORK_APP",
                        packageName = packageName,
                        timestamp = now,
                        data = gson.toJson(
                            mapOf(
                                "uid" to uid,
                                "rxBytesDelta" to rxDelta,
                                "txBytesDelta" to txDelta
                            )
                        )
                    )
                )
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to collect network stats: ${e.message}")
        }
    }

    private suspend fun collectSystemSnapshot() {
        try {
            val now = System.currentTimeMillis()
            val activityManager = getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
                ?: return
            val memInfo = ActivityManager.MemoryInfo()
            activityManager.getMemoryInfo(memInfo)

            val batteryManager = getSystemService(Context.BATTERY_SERVICE) as? BatteryManager
            val batteryPct = batteryManager
                ?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
                ?: -1

            database.behaviorEventDao().insert(
                BehaviorEvent(
                    eventType = "SYSTEM_STATE",
                    timestamp = now,
                    data = gson.toJson(
                        mapOf(
                            "availableMem" to memInfo.availMem,
                            "totalMem" to memInfo.totalMem,
                            "lowMemory" to memInfo.lowMemory,
                            "batteryPct" to batteryPct
                        )
                    )
                )
            )
        } catch (e: Exception) {
            Log.e(TAG, "Failed to collect system snapshot: ${e.message}")
        }
    }

    private suspend fun probeLogcatAccess() {
        try {
            val process = ProcessBuilder("logcat", "-d", "-t", "5")
                .redirectErrorStream(true)
                .start()

            val output = process.inputStream.bufferedReader().use { it.readText() }
            val exitCode = process.waitFor()
            val denied = output.contains("Permission Denial", ignoreCase = true) ||
                output.contains("not allowed", ignoreCase = true)

            val payload = if (denied || output.isBlank()) {
                mapOf(
                    "status" to "restricted",
                    "exitCode" to exitCode
                )
            } else {
                mapOf(
                    "status" to "available",
                    "exitCode" to exitCode,
                    "sample" to output.take(1000)
                )
            }

            database.behaviorEventDao().insert(
                BehaviorEvent(
                    eventType = "SYSTEM_LOGCAT_ACCESS",
                    timestamp = System.currentTimeMillis(),
                    data = gson.toJson(payload)
                )
            )
        } catch (e: Exception) {
            database.behaviorEventDao().insert(
                BehaviorEvent(
                    eventType = "SYSTEM_LOGCAT_ACCESS",
                    timestamp = System.currentTimeMillis(),
                    data = gson.toJson(
                        mapOf(
                            "status" to "error",
                            "message" to (e.message ?: "unknown")
                        )
                    )
                )
            )
        }
    }

    private fun registerSecurityReceivers() {
        if (receiversRegistered) return

        val authFilter = IntentFilter().apply {
            addAction(Intent.ACTION_USER_PRESENT)
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_SCREEN_OFF)
        }
        registerReceiver(authReceiver, authFilter)

        val packageFilter = IntentFilter().apply {
            addAction(Intent.ACTION_PACKAGE_ADDED)
            addAction(Intent.ACTION_PACKAGE_REMOVED)
            addAction(Intent.ACTION_PACKAGE_REPLACED)
            addDataScheme("package")
        }
        registerReceiver(packageReceiver, packageFilter)

        receiversRegistered = true
    }

    private fun unregisterSecurityReceivers() {
        if (!receiversRegistered) return
        try {
            unregisterReceiver(authReceiver)
        } catch (_: IllegalArgumentException) {
        }
        try {
            unregisterReceiver(packageReceiver)
        } catch (_: IllegalArgumentException) {
        }
        receiversRegistered = false
    }

    private fun persistSecurityEvent(
        eventType: String,
        payload: Map<String, Any?>,
        packageName: String? = null,
    ) {
        scope.launch {
            database.behaviorEventDao().insert(
                BehaviorEvent(
                    eventType = eventType,
                    packageName = packageName,
                    timestamp = System.currentTimeMillis(),
                    data = gson.toJson(payload)
                )
            )
        }
    }

    private suspend fun syncEvents() {
        val events = database.behaviorEventDao().getUnsynced(Config.EVENT_BATCH_SIZE)
        if (events.isEmpty()) return

        // Check WiFi connectivity
        val networkType = WiFiConnectivityMonitor.getNetworkTypeName(this)
        val isWiFi = WiFiConnectivityMonitor.isWiFiConnected(this)
        val isConnected = WiFiConnectivityMonitor.isNetworkConnected(this)

        if (!isConnected) {
            Log.w(TAG, "No network connection available. Events buffered for later sync.")
            return
        }

        if (!isWiFi) {
            Log.w(TAG, "Warning: Using $networkType instead of WiFi for data transmission (may incur charges)")
        }

        val payload = events.map { ev ->
            mapOf(
                "type" to ev.eventType,
                "packageName" to ev.packageName,
                "timestamp" to ev.timestamp,
                "data" to ev.data
            )
        }
        
        Log.d(TAG, "Syncing ${events.size} events via $networkType")
        webSocketClient?.sendEvents(payload)
        database.behaviorEventDao().markSynced(events.map { it.id })
        Log.i(TAG, "✓ Synced ${events.size} events via $networkType")
    }

    private fun handleServerMessage(text: String) {
        scope.launch {
            try {
                val msg = gson.fromJson(text, Map::class.java)
                if (msg["type"] == "alert") {
                    val alert = com.anomalydetector.data.model.Alert(
                        anomalyId = msg["anomalyId"] as? String ?: return@launch,
                        severity = (msg["severity"] as? Double)?.toInt() ?: 0,
                        threatType = msg["threatType"] as? String ?: "UNKNOWN",
                        message = msg["message"] as? String ?: "",
                        confidence = (msg["confidence"] as? Double)?.toFloat() ?: 0f,
                        actions = gson.toJson(msg["actions"]),
                    )
                    database.alertDao().insert(alert)
                    showAlertNotification(alert)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to parse server message: ${e.message}")
            }
        }
    }

    private fun showAlertNotification(alert: com.anomalydetector.data.model.Alert) {
        val notification = NotificationCompat.Builder(this, Config.CHANNEL_ALERTS)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("🚨 ${alert.threatType} — Severity ${alert.severity}/10")
            .setContentText(alert.message)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(PendingIntent.getActivity(
                this, 0,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE
            ))
            .build()

        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(Config.NOTIFICATION_ALERT_BASE + alert.severity, notification)
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, Config.CHANNEL_MONITORING)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("Anomaly Detector Active")
            .setContentText("Monitoring device behavior...")
            .setOngoing(true)
            .build()
    }

    private fun createNotificationChannels() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel(
            Config.CHANNEL_MONITORING, "Monitoring Service",
            NotificationManager.IMPORTANCE_LOW
        ))
        nm.createNotificationChannel(NotificationChannel(
            Config.CHANNEL_ALERTS, "Security Alerts",
            NotificationManager.IMPORTANCE_HIGH
        ))
    }

    private fun updateConnectionStatus(status: String) {
        getSharedPreferences(PREF_MONITORING, MODE_PRIVATE)
            .edit()
            .putString(KEY_CONNECTION_STATUS, status)
            .apply()

        sendBroadcast(Intent(ACTION_CONNECTION_STATUS).apply {
            setPackage(packageName)
            putExtra(EXTRA_CONNECTION_STATUS, status)
        })
    }

    companion object {
        private const val TAG = "MonitoringService"
        const val ACTION_CONNECTION_STATUS = "com.anomalydetector.CONNECTION_STATUS"
        const val EXTRA_CONNECTION_STATUS = "status"
        const val PREF_MONITORING = "monitoring_state"
        const val KEY_CONNECTION_STATUS = "connection_status"
        const val KEY_MONITORING_ENABLED = "monitoring_enabled"

        fun setMonitoringEnabled(context: Context, enabled: Boolean) {
            context.getSharedPreferences(PREF_MONITORING, MODE_PRIVATE)
                .edit()
                .putBoolean(KEY_MONITORING_ENABLED, enabled)
                .apply()
        }

        fun isMonitoringEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREF_MONITORING, MODE_PRIVATE)
            if (prefs.contains(KEY_MONITORING_ENABLED)) {
                return prefs.getBoolean(KEY_MONITORING_ENABLED, false)
            }

            // Backward compatibility: older builds persisted only connection_status.
            val lastStatus = prefs.getString(KEY_CONNECTION_STATUS, "Disconnected") ?: "Disconnected"
            return !lastStatus.equals("Disconnected", ignoreCase = true)
        }
    }
}
