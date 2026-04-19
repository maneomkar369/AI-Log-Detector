package com.anomalydetector.data.model

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Behavioral event captured from the device.
 *
 * Types include APP_USAGE, KEYSTROKE, TOUCH, SWIPE,
 * NETWORK_TRAFFIC, NETWORK_APP, SYSTEM_STATE,
 * SECURITY_AUTH_EVENT, SECURITY_PACKAGE_EVENT, SYSTEM_LOGCAT_ACCESS.
 */
@Entity(tableName = "behavior_events")
data class BehaviorEvent(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val eventType: String,
    val packageName: String? = null,
    val timestamp: Long = System.currentTimeMillis(),
    val data: String? = null,       // JSON payload
    val synced: Boolean = false,    // Has been sent to edge server
)
