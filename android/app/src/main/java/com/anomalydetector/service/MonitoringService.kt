package com.anomalydetector.service

import android.app.*
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
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

    override fun onCreate() {
        super.onCreate()
        createNotificationChannels()
        startForeground(Config.NOTIFICATION_MONITORING, buildNotification())
        startMonitoring()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        scope.cancel()
        webSocketClient?.disconnect()
        super.onDestroy()
    }

    private fun startMonitoring() {
        // Connect WebSocket
        val deviceId = android.provider.Settings.Secure.getString(
            contentResolver, android.provider.Settings.Secure.ANDROID_ID
        )
        webSocketClient = WebSocketClient(deviceId, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                Log.i(TAG, "WebSocket connected")
            }

            override fun onMessage(ws: WebSocket, text: String) {
                handleServerMessage(text)
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket error: ${t.message}")
                // Auto-reconnect after delay
                scope.launch {
                    delay(Config.RECONNECT_DELAY_MS)
                    webSocketClient?.connect()
                }
            }
        })
        webSocketClient?.connect()

        // Collect usage stats periodically
        scope.launch {
            while (isActive) {
                collectUsageStats()
                syncEvents()
                delay(Config.SAMPLING_INTERVAL_MS)
            }
        }
    }

    private suspend fun collectUsageStats() {
        try {
            val usm = getSystemService(Context.USAGE_STATS_SERVICE) as? UsageStatsManager
                ?: return

            val endTime = System.currentTimeMillis()
            val startTime = endTime - Config.SAMPLING_INTERVAL_MS

            val stats = usm.queryUsageStats(
                UsageStatsManager.INTERVAL_BEST, startTime, endTime
            )

            stats?.filter { it.totalTimeInForeground > 0 }?.forEach { stat ->
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
        } catch (e: Exception) {
            Log.e(TAG, "Failed to collect usage stats: ${e.message}")
        }
    }

    private suspend fun syncEvents() {
        val events = database.behaviorEventDao().getUnsynced(Config.EVENT_BATCH_SIZE)
        if (events.isEmpty()) return

        val payload = events.map { ev ->
            mapOf(
                "type" to ev.eventType,
                "packageName" to ev.packageName,
                "timestamp" to ev.timestamp,
                "data" to ev.data
            )
        }
        webSocketClient?.sendEvents(payload)
        database.behaviorEventDao().markSynced(events.map { it.id })
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

    companion object {
        private const val TAG = "MonitoringService"
    }
}
