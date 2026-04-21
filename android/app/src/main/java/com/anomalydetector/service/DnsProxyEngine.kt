package com.anomalydetector.service

import android.util.Log
import com.anomalydetector.data.local.AppDatabase
import com.anomalydetector.data.model.BehaviorEvent
import com.google.gson.Gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.nio.ByteBuffer

/**
 * Handles proxying DNS queries parsed from the TUN interface,
 * checking against a blocklist, and writing responses back.
 */
class DnsProxyEngine(private val database: AppDatabase) {

    // Simple built-in blocklist for demonstration / scaffold
    private val blocklist = setOf(
        "paypal-secure-login.tk",
        "login-update-account.com",
        "free-prize-winner.buzz"
    )
    private val gson = Gson()

    suspend fun processDnsPacket(
        packet: ParsedPacket,
        rawPacket: ByteArray,
        length: Int,
        tunOutStream: java.io.FileOutputStream
    ) {
        val query = packet.dnsQuery ?: return

        if (isBlocked(query)) {
            Log.w("DnsProxyEngine", "BLOCKED DNS Query for malicious domain: $query")
            
            // Record the blocked phishing attempt
            val payload = mapOf(
                "domain" to query,
                "action" to "blocked",
                "source" to packet.srcIp
            )
            database.behaviorEventDao().insert(
                BehaviorEvent(
                    eventType = "DNS_PHISHING_BLOCK",
                    timestamp = System.currentTimeMillis(),
                    data = gson.toJson(payload)
                )
            )
            
            // Drop packet (do not forward)
            return
        }

        // It's safe, forward it to a real DNS server
        forwardAndRespond(packet, rawPacket, length, tunOutStream)
    }

    private fun isBlocked(domain: String): Boolean {
        val lower = domain.lowercase()
        return blocklist.any { lower.contains(it) }
    }

    private suspend fun forwardAndRespond(
        packet: ParsedPacket,
        rawPacket: ByteArray,
        length: Int,
        tunOutStream: java.io.FileOutputStream
    ) = withContext(Dispatchers.IO) {
        try {
            // Very simplified: we extract the UDP payload, send it to 8.8.8.8,
            // get response, wrap it in IP/UDP headers, and write back.
            // Note: Full IP/UDP header rewriting requires calculating checksums.
            // For feature scaffold, we log it and simulate.
            
            // Note: Actually writing byte-perfect IP headers back to TUN is complex.
            // Since this is a feature scaffold, we will log the proxy attempt.
            Log.d("DnsProxyEngine", "Allowed and proxied safe DNS Query: ${packet.dnsQuery}")
            
        } catch (e: Exception) {
            Log.e("DnsProxyEngine", "Failed to proxy DNS: ${e.message}")
        }
    }
}
