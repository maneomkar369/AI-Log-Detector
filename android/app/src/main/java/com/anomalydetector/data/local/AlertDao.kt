package com.anomalydetector.data.local

import androidx.room.*
import com.anomalydetector.data.model.Alert
import kotlinx.coroutines.flow.Flow

@Dao
interface AlertDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(alert: Alert)

    @Query("SELECT * FROM alerts ORDER BY receivedAt DESC")
    fun getAllAlerts(): Flow<List<Alert>>

    @Query("SELECT * FROM alerts WHERE status = 'pending' ORDER BY severity DESC")
    fun getPendingAlerts(): Flow<List<Alert>>

    @Query("UPDATE alerts SET status = :status WHERE anomalyId = :anomalyId")
    suspend fun updateStatus(anomalyId: String, status: String)

    @Query("DELETE FROM alerts WHERE receivedAt < :before")
    suspend fun deleteOld(before: Long)

    @Query("DELETE FROM alerts")
    suspend fun deleteAll()
}
