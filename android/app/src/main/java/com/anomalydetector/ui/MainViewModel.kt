package com.anomalydetector.ui

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel

class MainViewModel : ViewModel() {
    private val _connectionStatus = MutableLiveData("Disconnected")
    val connectionStatus: LiveData<String> = _connectionStatus

    private val _lastSyncTime = MutableLiveData("Never")
    val lastSyncTime: LiveData<String> = _lastSyncTime

    fun updateConnectionStatus(status: String) {
        _connectionStatus.value = status
    }

    fun updateLastSyncTime(time: String) {
        _lastSyncTime.value = time
    }
}
