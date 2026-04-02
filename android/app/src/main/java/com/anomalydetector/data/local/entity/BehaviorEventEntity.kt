package com.anomalydetector.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "behavior_events")
data class BehaviorEventEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val timestamp: Long,
    val type: String,
    val packageName: String?,
    val data: String,
    val synced: Boolean = false,
    val retryCount: Int = 0
)
