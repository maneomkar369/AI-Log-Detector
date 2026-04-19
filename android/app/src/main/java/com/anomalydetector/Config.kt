package com.anomalydetector

/**
 * Global configuration constants.
 * Update SERVER_URL with your NGROK WebSocket URL.
 */
object Config {
    // Edge server WebSocket URL (update with your ngrok domain)
    var SERVER_URL = "wss://grid-scuff-diploma.ngrok-free.dev/ws"

    // Sampling & timing
    const val EVENT_BATCH_SIZE = 50
    var SAMPLING_INTERVAL_MS = 10_000L      // 10 seconds
    var RECONNECT_DELAY_MS = 5_000L          // 5 seconds
    var AUTO_APPROVAL_TIMEOUT_MS = 300_000L  // 5 minutes

    // VPN flow capture
    // Keep false unless you implement full packet forwarding to avoid traffic disruption.
    const val ENABLE_VPN_TUN_CAPTURE = true
    const val ENABLE_VPN_FORWARDER = true
    const val ENABLE_VPN_CAPTURE_WITHOUT_FORWARDING = false
    const val VPN_FORWARDER_COMMAND =
        "/data/local/tmp/tun2socks --tunfd %TUN_FD% --netif-ipaddr 10.42.0.2 " +
            "--netif-netmask 255.255.255.0 --socks-server-addr 127.0.0.1:1080"
    const val VPN_FLOW_FLUSH_INTERVAL_MS = 10_000L

    // Notification channels
    const val CHANNEL_MONITORING = "monitoring_channel"
    const val CHANNEL_ALERTS = "alerts_channel"
    const val CHANNEL_VPN = "vpn_flow_channel"

    // Notification IDs
    const val NOTIFICATION_MONITORING = 1001
    const val NOTIFICATION_ALERT_BASE = 2000
    const val NOTIFICATION_VPN = 3001
}
