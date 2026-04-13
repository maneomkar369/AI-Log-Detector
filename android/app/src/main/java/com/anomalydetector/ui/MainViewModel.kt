package com.anomalydetector.ui

import android.app.Application
import androidx.lifecycle.*
import com.anomalydetector.data.local.AlertDao
import com.anomalydetector.data.local.BehaviorEventDao
import com.anomalydetector.data.model.Alert
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class MainViewModel @Inject constructor(
    private val alertDao: AlertDao,
    private val eventDao: BehaviorEventDao,
) : ViewModel() {

    val alerts: LiveData<List<Alert>> = alertDao.getAllAlerts().asLiveData()
    val pendingAlerts: LiveData<List<Alert>> = alertDao.getPendingAlerts().asLiveData()
    val unsyncedCount: LiveData<Int> = eventDao.getUnsyncedCount().asLiveData()

    private val _isMonitoring = MutableLiveData(false)
    val isMonitoring: LiveData<Boolean> = _isMonitoring

    private val _connectionStatus = MutableLiveData("Disconnected")
    val connectionStatus: LiveData<String> = _connectionStatus

    fun setMonitoring(active: Boolean) {
        _isMonitoring.value = active
    }

    fun setConnectionStatus(status: String) {
        _connectionStatus.postValue(status)
    }

    fun approveAlert(anomalyId: String) {
        viewModelScope.launch {
            alertDao.updateStatus(anomalyId, "approved")
        }
    }

    fun denyAlert(anomalyId: String) {
        viewModelScope.launch {
            alertDao.updateStatus(anomalyId, "denied")
        }
    }
}
