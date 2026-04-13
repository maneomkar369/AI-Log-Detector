package com.anomalydetector.data.model

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Behavioral event captured from the device.
 *
 * Types: APP_USAGE, KEYSTROKE, TOUCH, SWIPE, LOCATION, NETWORK
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
