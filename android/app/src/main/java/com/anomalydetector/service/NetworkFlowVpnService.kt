package com.anomalydetector.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.VpnService
import android.os.IBinder
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.core.app.NotificationCompat
import com.anomalydetector.Config
import com.anomalydetector.data.local.AppDatabase
import com.anomalydetector.data.model.BehaviorEvent
import com.google.gson.Gson
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.FileInputStream
import java.io.IOException
import javax.inject.Inject

/**
 * VPN service scaffold for network flow metadata collection.
 *
 * Safe-mode behavior:
 * - By default, TUN capture is disabled (Config.ENABLE_VPN_TUN_CAPTURE=false)
 * - Service publishes status events without intercepting traffic.
 *
 * When explicitly enabled, it reads TUN packets and emits NETWORK_FLOW metadata
 * into Room, which MonitoringService syncs to backend.
 */
@AndroidEntryPoint
class NetworkFlowVpnService : VpnService() {

    @Inject lateinit var database: AppDatabase

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val gson = Gson()

    private var tunInterface: ParcelFileDescriptor? = null
    private var detachedTunFd: Int? = null
    private var captureJob: Job? = null
    private var flushJob: Job? = null
    private var forwarderWatchdogJob: Job? = null

    private val forwarder = ExternalTunForwarder()

    private val flowStats = mutableMapOf<String, FlowAggregate>()

    override fun onBind(intent: Intent?): IBinder? {
        return if (intent?.action == SERVICE_INTERFACE) {
            super.onBind(intent)
        } else {
            null
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startVpnFlow()
            ACTION_STOP -> stopVpnFlow("Stopped by user")
            else -> startVpnFlow()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        stopVpnFlow("Service destroyed")
        forwarder.shutdown()
        scope.cancel()
        super.onDestroy()
    }

    private fun startVpnFlow() {
        if (captureJob != null || tunInterface != null || detachedTunFd != null) {
            broadcastVpnStatus("VPN flow capture already running", active = true)
            return
        }

        // Flaw #19: VPN Conflict Detection
        if (isVpnAlreadyActive()) {
            scope.launch {
                persistStatusEvent(
                    status = "vpn_conflict",
                    message = "Another VPN is active. Network capture disabled to prevent conflict."
                )
            }
            broadcastVpnStatus("VPN Conflict: Capture disabled", active = false)
            updateNotification("Capture disabled: Another VPN is active")
            return
        }

        createNotificationChannel()
        startForeground(Config.NOTIFICATION_VPN, buildNotification("Starting VPN flow monitor..."))

        if (!Config.ENABLE_VPN_TUN_CAPTURE) {
            scope.launch {
                persistStatusEvent(
                    status = "safe_mode",
                    message = "VPN service started in safe mode (packet capture disabled)"
                )
            }
            broadcastVpnStatus("VPN safe mode active (capture disabled)", active = true)
            updateNotification("VPN safe mode active")
            return
        }

        val forwarderMode = Config.ENABLE_VPN_FORWARDER
        val captureWithoutForwardingMode = Config.ENABLE_VPN_CAPTURE_WITHOUT_FORWARDING

        if (!forwarderMode && !captureWithoutForwardingMode) {
            scope.launch {
                persistStatusEvent(
                    status = "safe_mode",
                    message = "Capture requested but no forwarder is enabled; staying in safe mode"
                )
            }
            broadcastVpnStatus("VPN safe mode active (forwarder disabled)", active = true)
            updateNotification("VPN safe mode active (forwarder disabled)")
            return
        }

        val builder = Builder()
            .setSession("AnomalyDetectorFlow")
            .setMtu(1500)
            .addAddress("10.42.0.2", 32)
            .addRoute("0.0.0.0", 0)
            .addDnsServer("8.8.8.8")

        try {
            builder.addDisallowedApplication(packageName)
        } catch (_: Exception) {
            // Optional optimization; ignore if unsupported.
        }

        val iface = builder.establish()
        if (iface == null) {
            scope.launch {
                persistStatusEvent(
                    status = "error",
                    message = "Failed to establish VPN interface"
                )
            }
            broadcastVpnStatus("Failed to establish VPN interface", active = false)
            stopSelf()
            return
        }

        if (forwarderMode) {
            val fd = iface.detachFd()
            detachedTunFd = fd
            tunInterface = null

            val started = forwarder.start(Config.VPN_FORWARDER_COMMAND, fd)
            if (!started) {
                closeDetachedTunFd()
                scope.launch {
                    persistStatusEvent(
                        status = "error",
                        message = "Forwarder failed to start; VPN stopped"
                    )
                }
                broadcastVpnStatus("VPN forwarder failed to start", active = false)
                stopSelf()
                return
            }

            scope.launch {
                persistStatusEvent(
                    status = "forwarding",
                    message = "VPN forwarding active via external forwarder"
                )
            }
            broadcastVpnStatus("VPN forwarding active", active = true)
            updateNotification("VPN forwarding active")

            forwarderWatchdogJob = scope.launch {
                while (isActive) {
                    delay(2000)
                    if (!forwarder.isAlive()) {
                        persistStatusEvent(
                            status = "error",
                            message = "Forwarder process exited unexpectedly"
                        )
                        broadcastVpnStatus("VPN forwarder stopped unexpectedly", active = false)
                        stopSelf()
                        break
                    }
                }
            }
            return
        }

        tunInterface = iface
        broadcastVpnStatus("VPN packet capture running (no forwarding)", active = true)
        updateNotification("VPN packet capture running (no forwarding)")

        captureJob = scope.launch {
            capturePacketsLoop(iface)
        }
        flushJob = scope.launch {
            while (isActive) {
                delay(Config.VPN_FLOW_FLUSH_INTERVAL_MS)
                flushFlowStats()
            }
        }
    }

    private fun stopVpnFlow(reason: String) {
        captureJob?.cancel()
        flushJob?.cancel()
        forwarderWatchdogJob?.cancel()
        captureJob = null
        flushJob = null
        forwarderWatchdogJob = null

        forwarder.stop()

        try {
            tunInterface?.close()
        } catch (_: Exception) {
        }
        tunInterface = null
        closeDetachedTunFd()

        scope.launch {
            flushFlowStats()
            persistStatusEvent(status = "stopped", message = reason)
        }

        broadcastVpnStatus("VPN flow capture stopped", active = false)
        stopForeground(STOP_FOREGROUND_REMOVE)
    }

    private fun closeDetachedTunFd() {
        val fd = detachedTunFd ?: return
        try {
            ParcelFileDescriptor.adoptFd(fd).close()
        } catch (e: IOException) {
            Log.w(TAG, "Failed to close detached TUN fd: ${e.message}")
        }
        detachedTunFd = null
    }

    private val dnsProxyEngine by lazy { DnsProxyEngine(database) }

    private suspend fun capturePacketsLoop(iface: ParcelFileDescriptor) {
        try {
            FileInputStream(iface.fileDescriptor).use { input ->
                val outStream = java.io.FileOutputStream(iface.fileDescriptor)
                val buffer = ByteArray(32767)
                while (scope.isActive && tunInterface != null) {
                    val read = input.read(buffer)
                    if (read <= 0) continue

                    val packet = VpnPacketParser.parse(buffer, read) ?: continue
                    
                    // Route DNS queries to the proxy engine
                    if (packet.dnsQuery != null) {
                        dnsProxyEngine.processDnsPacket(packet, buffer, read, outStream)
                        // In strict DNS blocking mode, we might only log DNS packets.
                    }

                    val key = "${packet.protocol}|${packet.dstIp}|${packet.dstPort ?: 0}"

                    synchronized(flowStats) {
                        val existing = flowStats[key]
                        if (existing == null) {
                            flowStats[key] = FlowAggregate(
                                protocol = packet.protocol,
                                srcIp = packet.srcIp,
                                dstIp = packet.dstIp,
                                srcPort = packet.srcPort,
                                dstPort = packet.dstPort,
                                packetCount = 1,
                                totalBytes = packet.bytes.toLong(),
                            )
                        } else {
                            flowStats[key] = existing.copy(
                                packetCount = existing.packetCount + 1,
                                totalBytes = existing.totalBytes + packet.bytes,
                            )
                        }
                    }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "VPN capture loop failed: ${e.message}")
            persistStatusEventAsync("error", "VPN capture loop error: ${e.message}")
            broadcastVpnStatus("VPN capture error", active = false)
            stopSelf()
        }
    }

    private suspend fun flushFlowStats() {
        val snapshot = synchronized(flowStats) {
            val copy = flowStats.values.toList()
            flowStats.clear()
            copy
        }

        if (snapshot.isEmpty()) return

        val now = System.currentTimeMillis()
        val topFlows = snapshot
            .sortedByDescending { it.totalBytes }
            .take(30)

        topFlows.forEach { flow ->
            val payload = mapOf(
                "protocol" to flow.protocol,
                "srcIp" to flow.srcIp,
                "dstIp" to flow.dstIp,
                "srcPort" to flow.srcPort,
                "dstPort" to flow.dstPort,
                "packetCount" to flow.packetCount,
                "bytes" to flow.totalBytes,
            )
            database.behaviorEventDao().insert(
                BehaviorEvent(
                    eventType = "NETWORK_FLOW",
                    timestamp = now,
                    data = gson.toJson(payload)
                )
            )
        }
    }

    private suspend fun persistStatusEvent(status: String, message: String) {
        database.behaviorEventDao().insert(
            BehaviorEvent(
                eventType = "NETWORK_FLOW_STATUS",
                timestamp = System.currentTimeMillis(),
                data = gson.toJson(
                    mapOf(
                        "status" to status,
                        "message" to message,
                    )
                )
            )
        )
    }

    private fun persistStatusEventAsync(status: String, message: String) {
        scope.launch {
            persistStatusEvent(status, message)
        }
    }

    private fun isVpnAlreadyActive(): Boolean {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = cm.activeNetwork ?: return false
        val capabilities = cm.getNetworkCapabilities(network) ?: return false
        return capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN)
    }

    private fun buildNotification(content: String): Notification {
        return NotificationCompat.Builder(this, Config.CHANNEL_VPN)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle("VPN Flow Monitor")
            .setContentText(content)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(content: String) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(Config.NOTIFICATION_VPN, buildNotification(content))
    }

    private fun createNotificationChannel() {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(
                Config.CHANNEL_VPN,
                "VPN Flow Monitor",
                NotificationManager.IMPORTANCE_LOW,
            )
        )
    }

    private fun broadcastVpnStatus(status: String, active: Boolean) {
        getSharedPreferences(PREF_VPN, MODE_PRIVATE)
            .edit()
            .putString(KEY_VPN_STATUS, status)
            .putBoolean(KEY_VPN_ACTIVE, active)
            .apply()

        sendBroadcast(Intent(ACTION_VPN_STATUS).apply {
            setPackage(packageName)
            putExtra(EXTRA_VPN_STATUS, status)
            putExtra(EXTRA_VPN_ACTIVE, active)
        })
    }

    companion object {
        private const val TAG = "NetworkFlowVpnService"

        const val ACTION_START = "com.anomalydetector.action.START_VPN_FLOW"
        const val ACTION_STOP = "com.anomalydetector.action.STOP_VPN_FLOW"

        const val ACTION_VPN_STATUS = "com.anomalydetector.VPN_STATUS"
        const val EXTRA_VPN_STATUS = "vpn_status"
        const val EXTRA_VPN_ACTIVE = "vpn_active"

        const val PREF_VPN = "vpn_state"
        const val KEY_VPN_STATUS = "vpn_status"
        const val KEY_VPN_ACTIVE = "vpn_active"
    }
}

data class FlowAggregate(
    val protocol: String,
    val srcIp: String,
    val dstIp: String,
    val srcPort: Int?,
    val dstPort: Int?,
    val packetCount: Int,
    val totalBytes: Long,
)
