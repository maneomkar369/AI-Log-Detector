package com.anomalydetector.service

/**
 * Minimal IPv4 packet parser for TUN packet metadata extraction.
 *
 * This parser is intentionally lightweight and used only to build
 * flow-level metadata (protocol/ip/port/bytes), not payload inspection.
 */
data class ParsedPacket(
    val protocol: String,
    val srcIp: String,
    val dstIp: String,
    val srcPort: Int?,
    val dstPort: Int?,
    val bytes: Int,
    val dnsQuery: String? = null
)

object VpnPacketParser {
    fun parse(buffer: ByteArray, length: Int): ParsedPacket? {
        if (length < 20) return null

        val version = (u8(buffer[0]) ushr 4) and 0x0F
        if (version != 4) return null

        val ihl = (u8(buffer[0]) and 0x0F) * 4
        if (ihl < 20 || length < ihl) return null

        val protocolNumber = u8(buffer[9])
        val protocol = when (protocolNumber) {
            6 -> "TCP"
            17 -> "UDP"
            1 -> "ICMP"
            else -> "IP_$protocolNumber"
        }

        val srcIp = ipv4(buffer, 12)
        val dstIp = ipv4(buffer, 16)

        var srcPort: Int? = null
        var dstPort: Int? = null
        if ((protocolNumber == 6 || protocolNumber == 17) && length >= ihl + 4) {
            srcPort = (u8(buffer[ihl]) shl 8) or u8(buffer[ihl + 1])
            dstPort = (u8(buffer[ihl + 2]) shl 8) or u8(buffer[ihl + 3])
        }

        var dnsQuery: String? = null
        if (protocolNumber == 17 && dstPort == 53 && length >= ihl + 8 + 12) {
            val udpPayloadOffset = ihl + 8
            val flags = (u8(buffer[udpPayloadOffset + 2]) shl 8) or u8(buffer[udpPayloadOffset + 3])
            val isQuery = (flags and 0x8000) == 0
            if (isQuery) {
                try {
                    dnsQuery = parseDnsQname(buffer, udpPayloadOffset + 12, length)
                } catch (e: Exception) {
                    // Ignore malformed DNS
                }
            }
        }

        return ParsedPacket(
            protocol = protocol,
            srcIp = srcIp,
            dstIp = dstIp,
            srcPort = srcPort,
            dstPort = dstPort,
            bytes = length,
            dnsQuery = dnsQuery
        )
    }

    private fun parseDnsQname(buffer: ByteArray, offset: Int, length: Int): String? {
        var current = offset
        val sb = StringBuilder()
        var jumps = 0
        while (current < length && jumps < 10) {
            val len = u8(buffer[current])
            if (len == 0) break
            if ((len and 0xC0) == 0xC0) break // Ignore compression in simple parser
            if (sb.isNotEmpty()) sb.append(".")
            current++
            if (current + len > length) return null
            for (i in 0 until len) {
                sb.append(buffer[current + i].toInt().toChar())
            }
            current += len
            jumps++
        }
        return if (sb.isNotEmpty()) sb.toString() else null
    }

    private fun ipv4(buffer: ByteArray, offset: Int): String {
        return "${u8(buffer[offset])}.${u8(buffer[offset + 1])}.${u8(buffer[offset + 2])}.${u8(buffer[offset + 3])}"
    }

    private fun u8(value: Byte): Int = value.toInt() and 0xFF
}
