package com.anomalydetector.ui

import android.app.Application
import androidx.lifecycle.*
import com.anomalydetector.data.local.AlertDao
import com.anomalydetector.data.local.BehaviorEventDao
import com.anomalydetector.data.model.Alert
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import android.util.Log
import okhttp3.RequestBody.Companion.toRequestBody
import javax.inject.Inject

@HiltViewModel
class MainViewModel @Inject constructor(
    application: Application,
    private val alertDao: AlertDao,
    private val eventDao: BehaviorEventDao,
) : AndroidViewModel(application) {

    val alerts: LiveData<List<Alert>> = alertDao.getAllAlerts().asLiveData()
    val pendingAlerts: LiveData<List<Alert>> = alertDao.getPendingAlerts().asLiveData()
    val unsyncedCount: LiveData<Int> = eventDao.getUnsyncedCount().asLiveData()

    private val _isMonitoring = MutableLiveData(false)
    val isMonitoring: LiveData<Boolean> = _isMonitoring

    private val _connectionStatus = MutableLiveData("Disconnected")
    val connectionStatus: LiveData<String> = _connectionStatus

    private val _isVpnActive = MutableLiveData(false)
    val isVpnActive: LiveData<Boolean> = _isVpnActive

    private val _vpnStatus = MutableLiveData("VPN flow: inactive")
    val vpnStatus: LiveData<String> = _vpnStatus

    fun setMonitoring(active: Boolean) {
        _isMonitoring.value = active
    }

    fun setConnectionStatus(status: String) {
        _connectionStatus.postValue(status)
    }

    fun setVpnStatus(status: String) {
        _vpnStatus.postValue(status)
    }

    fun setVpnActive(active: Boolean) {
        _isVpnActive.postValue(active)
    }

    fun approveAlert(anomalyId: String) {
        viewModelScope.launch(Dispatchers.IO) {
            alertDao.updateStatus(anomalyId, "approved")
            try {
                val baseUrl = getApiBaseUrl()
                val client = okhttp3.OkHttpClient()
                val request = okhttp3.Request.Builder()
                    .url("$baseUrl/api/alerts/$anomalyId/approve")
                    .post(ByteArray(0).toRequestBody(null))
                    .build()
                val response = client.newCall(request).execute()
                Log.i("MainViewModel", "Approve alert $anomalyId sync: ${response.isSuccessful}")
            } catch (e: Exception) {
                Log.e("MainViewModel", "Failed to sync approveAlert to server: ${e.message}")
            }
        }
    }

    fun denyAlert(anomalyId: String) {
        viewModelScope.launch(Dispatchers.IO) {
            alertDao.updateStatus(anomalyId, "denied")
            try {
                val baseUrl = getApiBaseUrl()
                val client = okhttp3.OkHttpClient()
                val request = okhttp3.Request.Builder()
                    .url("$baseUrl/api/alerts/$anomalyId/deny")
                    .post(ByteArray(0).toRequestBody(null))
                    .build()
                val response = client.newCall(request).execute()
                Log.i("MainViewModel", "Deny alert $anomalyId sync: ${response.isSuccessful}")
            } catch (e: Exception) {
                Log.e("MainViewModel", "Failed to sync denyAlert to server: ${e.message}")
            }
        }
    }

    private fun getApiBaseUrl(): String {
        return com.anomalydetector.Config.SERVER_URL
            .replace("ws://", "http://")
            .replace("wss://", "https://")
            .substringBeforeLast("/ws")
    }

    fun markNormal(anomalyId: String) {
        viewModelScope.launch(Dispatchers.IO) {
            alertDao.updateStatus(anomalyId, "normal")
            try {
                val baseUrl = getApiBaseUrl()
                val client = okhttp3.OkHttpClient()
                val request = okhttp3.Request.Builder()
                    .url("$baseUrl/api/alerts/$anomalyId/mark_normal")
                    .post(ByteArray(0).toRequestBody(null))
                    .build()
                val response = client.newCall(request).execute()
                Log.i("MainViewModel", "Mark normal $anomalyId sync: ${response.isSuccessful}")
            } catch (e: Exception) {
                android.util.Log.e("MainViewModel", "Failed to sync markNormal to server: ${e.message}")
            }
        }
    }

    fun clearAllAlerts() {
        viewModelScope.launch(Dispatchers.IO) {
            alertDao.deleteAll()
            try {
                val androidId = android.provider.Settings.Secure.getString(
                    getApplication<Application>().contentResolver,
                    android.provider.Settings.Secure.ANDROID_ID
                )
                val baseUrl = getApiBaseUrl()
                val client = okhttp3.OkHttpClient()
                val request = okhttp3.Request.Builder()
                    .url("$baseUrl/api/alerts/$androidId")
                    .delete()
                    .build()
                val response = client.newCall(request).execute()
                Log.i("MainViewModel", "Clear all alerts sync: ${response.isSuccessful}")
            } catch (e: Exception) {
                Log.e("MainViewModel", "Failed to sync clearAllAlerts to server: ${e.message}")
            }
        }
    }
}
