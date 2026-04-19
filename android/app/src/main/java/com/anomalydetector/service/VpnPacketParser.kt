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

        return ParsedPacket(
            protocol = protocol,
            srcIp = srcIp,
            dstIp = dstIp,
            srcPort = srcPort,
            dstPort = dstPort,
            bytes = length,
        )
    }

    private fun ipv4(buffer: ByteArray, offset: Int): String {
        return "${u8(buffer[offset])}.${u8(buffer[offset + 1])}.${u8(buffer[offset + 2])}.${u8(buffer[offset + 3])}"
    }

    private fun u8(value: Byte): Int = value.toInt() and 0xFF
}
