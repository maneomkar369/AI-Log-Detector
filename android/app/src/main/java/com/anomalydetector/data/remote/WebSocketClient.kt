package com.anomalydetector.data.remote

import android.util.Log
import com.anomalydetector.Config
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import okhttp3.*
import java.util.concurrent.TimeUnit

/**
 * WebSocket client for communicating with the edge server.
 *
 * Handles:
 * - Connection management with auto-reconnect
 * - Sending batched behavioral events as JSON arrays
 * - Receiving alert messages from the server
 */
class WebSocketClient(
    private val deviceId: String,
    private val listener: WebSocketListener
) {
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)  // No timeout for WebSocket
        .pingInterval(30, TimeUnit.SECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private val gson = Gson()

    val isConnected: Boolean get() = webSocket != null

    fun connect() {
        val url = "${Config.SERVER_URL}/$deviceId"
        Log.i(TAG, "Connecting to $url")

        val request = Request.Builder()
            .url(url)
            .build()

        webSocket = client.newWebSocket(request, listener)
    }

    fun disconnect() {
        webSocket?.close(1000, "Client disconnect")
        webSocket = null
    }

    fun sendEvents(events: List<Map<String, Any?>>) {
        val json = gson.toJson(events)
        webSocket?.send(json)
        Log.d(TAG, "Sent ${events.size} events (${json.length} bytes)")
    }

    fun sendApproval(anomalyId: String) {
        val msg = gson.toJson(mapOf(
            "type" to "approval",
            "anomalyId" to anomalyId,
            "action" to "approve"
        ))
        webSocket?.send(msg)
    }

    fun sendDenial(anomalyId: String) {
        val msg = gson.toJson(mapOf(
            "type" to "approval",
            "anomalyId" to anomalyId,
            "action" to "deny"
        ))
        webSocket?.send(msg)
    }

    companion object {
        private const val TAG = "WebSocketClient"
    }
}
