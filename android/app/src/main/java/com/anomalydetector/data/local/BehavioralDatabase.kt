package com.anomalydetector.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import com.anomalydetector.data.local.dao.AlertDao
import com.anomalydetector.data.local.dao.BehaviorEventDao
import com.anomalydetector.data.local.entity.AlertEntity
import com.anomalydetector.data.local.entity.BehaviorEventEntity

@Database(
    entities = [BehaviorEventEntity::class, AlertEntity::class],
    version = 1,
    exportSchema = false
)
abstract class BehavioralDatabase : RoomDatabase() {
    abstract fun behaviorEventDao(): BehaviorEventDao
    abstract fun alertDao(): AlertDao
}
