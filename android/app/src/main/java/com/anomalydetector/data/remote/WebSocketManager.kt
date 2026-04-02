package com.anomalydetector.data.remote

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import okhttp3.*
import okhttp3.Request

class WebSocketManager(
    private val okHttpClient: OkHttpClient = OkHttpClient(),
) {
    private var webSocket: WebSocket? = null
    private val _alerts = MutableSharedFlow<String>(extraBufferCapacity = 64)
    val alerts: SharedFlow<String> = _alerts

    fun connect(baseUrl: String, deviceId: String) {
        val request = Request.Builder()
            .url("$baseUrl/ws/$deviceId")
            .build()

        webSocket = okHttpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                _alerts.tryEmit(text)
            }
        })
    }

    fun send(message: String): Boolean = webSocket?.send(message) ?: false

    fun disconnect() {
        webSocket?.close(1000, "client_close")
        webSocket = null
    }
}
