package com.anomalydetector.service

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.util.Log

/**
 * WiFi Connectivity Monitor
 * Checks device WiFi status and warns if using cellular data instead.
 */
object WiFiConnectivityMonitor {
    private const val TAG = "WiFiMonitor"

    /**
     * Check if device is connected to WiFi network.
     */
    fun isWiFiConnected(context: Context): Boolean {
        try {
            val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
                ?: return false

            val network = connectivityManager.activeNetwork ?: return false
            val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return false

            return capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
        } catch (e: Exception) {
            Log.e(TAG, "Error checking WiFi status: ${e.message}")
            return false
        }
    }

    /**
     * Check if device is connected to any network.
     */
    fun isNetworkConnected(context: Context): Boolean {
        try {
            val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
                ?: return false

            val network = connectivityManager.activeNetwork ?: return false
            val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return false

            return capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ||
                    capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                    capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
        } catch (e: Exception) {
            Log.e(TAG, "Error checking network status: ${e.message}")
            return false
        }
    }

    /**
     * Get network type name for logging.
     */
    fun getNetworkTypeName(context: Context): String {
        return when {
            isWiFiConnected(context) -> "WiFi"
            else -> {
                try {
                    val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
                    val network = connectivityManager?.activeNetwork
                    val capabilities = connectivityManager?.getNetworkCapabilities(network)

                    when {
                        capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true -> "Cellular"
                        capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) == true -> "Ethernet"
                        else -> "Unknown"
                    }
                } catch (e: Exception) {
                    "Unknown"
                }
            }
        }
    }

    /**
     * Log network connectivity status.
     */
    fun logNetworkStatus(context: Context) {
        val wifiConnected = isWiFiConnected(context)
        val networkConnected = isNetworkConnected(context)
        val networkType = getNetworkTypeName(context)

        Log.i(TAG, "Network Status - WiFi: $wifiConnected | Connected: $networkConnected | Type: $networkType")
    }
}
