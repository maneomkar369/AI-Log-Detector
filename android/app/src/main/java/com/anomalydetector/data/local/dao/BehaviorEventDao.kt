package com.anomalydetector.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.anomalydetector.data.local.entity.BehaviorEventEntity

@Dao
interface BehaviorEventDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(event: BehaviorEventEntity)

    @Query("SELECT * FROM behavior_events WHERE synced = 0 ORDER BY timestamp ASC LIMIT :limit")
    suspend fun getUnsynced(limit: Int = 200): List<BehaviorEventEntity>

    @Query("UPDATE behavior_events SET synced = 1 WHERE id IN (:ids)")
    suspend fun markSynced(ids: List<Long>)
}
