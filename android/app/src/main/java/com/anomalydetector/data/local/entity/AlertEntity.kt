package com.anomalydetector.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "alerts")
data class AlertEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val anomalyId: String,
    val timestamp: Long,
    val severity: String,
    val threatType: String,
    val message: String,
    val status: String
)
