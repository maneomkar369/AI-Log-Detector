package com.anomalydetector.data

import com.anomalydetector.data.local.dao.AlertDao
import com.anomalydetector.data.local.dao.BehaviorEventDao
import com.anomalydetector.data.local.entity.AlertEntity
import com.anomalydetector.data.local.entity.BehaviorEventEntity
import com.anomalydetector.data.remote.WebSocketManager
import kotlinx.coroutines.flow.SharedFlow

class BehaviorRepository(
    private val behaviorEventDao: BehaviorEventDao,
    private val alertDao: AlertDao,
    private val webSocketManager: WebSocketManager,
) {
    val incomingAlerts: SharedFlow<String> = webSocketManager.alerts

    suspend fun bufferBehavior(event: BehaviorEventEntity) {
        behaviorEventDao.insert(event)
    }

    suspend fun saveAlert(alert: AlertEntity) {
        alertDao.insert(alert)
    }

    suspend fun getRecentAlerts(limit: Int = 50): List<AlertEntity> {
        return alertDao.getRecent(limit)
    }

    fun connectEdge(wsBaseUrl: String, deviceId: String) {
        webSocketManager.connect(wsBaseUrl, deviceId)
    }

    fun sendApproval(payload: String): Boolean {
        return webSocketManager.send(payload)
    }
}
