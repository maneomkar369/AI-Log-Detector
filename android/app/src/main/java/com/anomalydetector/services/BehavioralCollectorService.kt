package com.anomalydetector.services

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder

class BehavioralCollectorService : Service() {

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startForeground(1001, buildNotification())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                "behavioral_collector",
                "Behavioral Monitoring",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, "behavioral_collector")
        } else {
            Notification.Builder(this)
        }
        return builder
            .setContentTitle("Behavioral monitoring active")
            .setContentText("Collecting usage events")
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .build()
    }
}
