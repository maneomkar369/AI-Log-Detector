package com.anomalydetector.data.local

import androidx.room.*
import com.anomalydetector.data.model.BehaviorEvent
import kotlinx.coroutines.flow.Flow

@Dao
interface BehaviorEventDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(event: BehaviorEvent)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(events: List<BehaviorEvent>)

    @Query("SELECT * FROM behavior_events WHERE synced = 0 ORDER BY timestamp ASC LIMIT :limit")
    suspend fun getUnsynced(limit: Int = 50): List<BehaviorEvent>

    @Query("UPDATE behavior_events SET synced = 1 WHERE id IN (:ids)")
    suspend fun markSynced(ids: List<Long>)

    @Query("SELECT COUNT(*) FROM behavior_events WHERE synced = 0")
    fun getUnsyncedCount(): Flow<Int>

    @Query("DELETE FROM behavior_events WHERE synced = 1 AND timestamp < :before")
    suspend fun deleteOldSynced(before: Long)
}
