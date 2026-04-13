package com.anomalydetector.data.model

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Alert received from the edge server.
 */
@Entity(tableName = "alerts")
data class Alert(
    @PrimaryKey
    val anomalyId: String,
    val severity: Int,
    val threatType: String,
    val message: String,
    val confidence: Float,
    val actions: String? = null,   // JSON array of action strings
    val status: String = "pending", // pending, approved, denied, snoozed
    val receivedAt: Long = System.currentTimeMillis(),
)
