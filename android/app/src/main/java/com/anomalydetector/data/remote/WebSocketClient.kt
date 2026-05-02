package com.anomalydetector.data.remote

import android.util.Log
import com.anomalydetector.Config
import com.google.gson.Gson
import okhttp3.*
import java.util.concurrent.TimeUnit
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * WebSocket client for communicating with the edge server.
 *
 * Handles:
 * - Connection management with auto-reconnect and URL fallback
 * - Sending batched behavioral events as JSON arrays
 * - Receiving alert messages from the server
 * - Smart reconnection: tries LOCAL first, then NGROK
 */
class WebSocketClient(
    private val deviceId: String,
    private val listener: WebSocketListener
) {
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)  // No timeout for WebSocket
        .pingInterval(30, TimeUnit.SECONDS)
        .connectTimeout(10, TimeUnit.SECONDS)    // 10s connect timeout for fast fallback
        .build()

    private var webSocket: WebSocket? = null
    private val gson = Gson()

    // URL fallback: local first, then ngrok
    private val serverUrls = listOf(Config.LOCAL_SERVER_URL, Config.NGROK_SERVER_URL)
    private var currentUrlIndex = 0
    private var consecutiveFailures = 0

    val isConnected: Boolean get() = webSocket != null

    fun connect() {
        val baseUrl = serverUrls[currentUrlIndex]
        val hmacToken = generateHmac(deviceId)
        val url = "$baseUrl/$deviceId?token=$hmacToken"
        Log.i(TAG, "Connecting to $url (attempt via ${if (currentUrlIndex == 0) "LOCAL" else "NGROK"})")

        val request = Request.Builder()
            .url(url)
            .build()

        // Wrap the user listener to intercept failures for fallback
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                consecutiveFailures = 0
                Config.SERVER_URL = baseUrl
                Log.i(TAG, "✓ Connected via ${if (currentUrlIndex == 0) "LOCAL" else "NGROK"}: $baseUrl")
                listener.onOpen(webSocket, response)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                listener.onMessage(webSocket, text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                listener.onClosing(webSocket, code, reason)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                this@WebSocketClient.webSocket = null
                listener.onClosed(webSocket, code, reason)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                this@WebSocketClient.webSocket = null
                consecutiveFailures++

                val statusCode = response?.code
                Log.w(TAG, "Connection failed (${if (currentUrlIndex == 0) "LOCAL" else "NGROK"}): " +
                        "${t.message}, HTTP=$statusCode, failures=$consecutiveFailures")

                // If we get a connection error, switch to the other URL
                val isNetworkError = t is java.net.ConnectException || 
                                     t is java.net.SocketTimeoutException ||
                                     t is java.net.UnknownHostException ||
                                     t.message?.contains("refused") == true ||
                                     t.message?.contains("Failed to connect") == true ||
                                     t.message?.contains("timeout") == true ||
                                     t.message?.contains("unreachable") == true

                if (statusCode == 404 || isNetworkError || consecutiveFailures >= 2) {

                    // Switch to the other URL
                    val nextIndex = (currentUrlIndex + 1) % serverUrls.size
                    if (nextIndex != currentUrlIndex || consecutiveFailures > 2) {
                        currentUrlIndex = nextIndex
                        Log.i(TAG, "Switching to ${if (currentUrlIndex == 0) "LOCAL" else "NGROK"} URL")
                    }
                }

                // Delegate to original listener for reconnect scheduling
                listener.onFailure(webSocket, t, response)
            }
        })
    }

    private fun generateHmac(data: String): String {
        try {
            val secretKeySpec = SecretKeySpec(Config.DEVICE_SHARED_SECRET.toByteArray(), "HmacSHA256")
            val mac = Mac.getInstance("HmacSHA256")
            mac.init(secretKeySpec)
            val bytes = mac.doFinal(data.toByteArray())
            return bytes.joinToString("") { "%02x".format(it) }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to generate HMAC", e)
            return ""
        }
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

    /** Reset to try local URL first on next connect attempt. */
    fun resetFallback() {
        currentUrlIndex = 0
        consecutiveFailures = 0
    }

    companion object {
        private const val TAG = "WebSocketClient"
    }
}
