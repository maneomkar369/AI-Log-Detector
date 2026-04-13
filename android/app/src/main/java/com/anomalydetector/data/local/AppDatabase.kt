package com.anomalydetector.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import com.anomalydetector.data.model.BehaviorEvent
import com.anomalydetector.data.model.Alert

@Database(
    entities = [BehaviorEvent::class, Alert::class],
    version = 1,
    exportSchema = false
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun behaviorEventDao(): BehaviorEventDao
    abstract fun alertDao(): AlertDao
}
