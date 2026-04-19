package com.anomalydetector.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Restarts monitoring after boot/package update when the user previously enabled monitoring.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        if (action !in RESTART_ACTIONS) {
            return
        }

        if (!MonitoringService.isMonitoringEnabled(context)) {
            Log.i(TAG, "Monitoring auto-start skipped; user has monitoring disabled")
            return
        }

        try {
            context.startForegroundService(Intent(context, MonitoringService::class.java))
            Log.i(TAG, "Monitoring auto-started after broadcast: $action")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to auto-start monitoring after $action: ${e.message}")
        }
    }

    companion object {
        private const val TAG = "BootReceiver"
        private val RESTART_ACTIONS = setOf(
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            Intent.ACTION_LOCKED_BOOT_COMPLETED,
        )
    }
}
