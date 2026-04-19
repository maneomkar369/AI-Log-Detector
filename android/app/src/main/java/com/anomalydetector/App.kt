package com.anomalydetector

import android.app.Application
import android.content.Intent
import android.util.Log
import com.anomalydetector.service.MonitoringService
import dagger.hilt.android.HiltAndroidApp

/**
 * Application class — initializes Hilt dependency injection.
 */
@HiltAndroidApp
class App : Application() {
    override fun onCreate() {
        super.onCreate()

        val prefs = getSharedPreferences("settings", MODE_PRIVATE)
        Config.SERVER_URL = prefs.getString("server_url", Config.SERVER_URL) ?: Config.SERVER_URL
        Config.SAMPLING_INTERVAL_MS = prefs.getLong("sampling_interval_ms", Config.SAMPLING_INTERVAL_MS)
        Config.RECONNECT_DELAY_MS = prefs.getLong("reconnect_delay_ms", Config.RECONNECT_DELAY_MS)
        Config.AUTO_APPROVAL_TIMEOUT_MS =
            prefs.getLong("auto_approval_timeout_ms", Config.AUTO_APPROVAL_TIMEOUT_MS)

        if (MonitoringService.isMonitoringEnabled(this)) {
            try {
                startForegroundService(Intent(this, MonitoringService::class.java))
            } catch (e: Exception) {
                Log.w("BAD-App", "Failed to auto-start monitoring on app launch: ${e.message}")
            }
        }
    }
}
