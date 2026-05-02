package com.anomalydetector

/**
 * Global configuration constants.
 * The app tries LOCAL_SERVER_URL first (same WiFi network),
 * then falls back to NGROK_SERVER_URL (remote tunnel).
 */
object Config {
    // ── Server URLs (ordered by priority) ──
    // Local edge server on same WiFi network
    var LOCAL_SERVER_URL = "ws://10.124.130.168:8000/ws"

    // Remote ngrok tunnel (fallback when not on same network)
    var NGROK_SERVER_URL = "wss://grid-scuff-diploma.ngrok-free.dev/ws"

    // Active URL (set dynamically by WebSocketClient during connection)
    var SERVER_URL = LOCAL_SERVER_URL

    // Flaw #16: Shared secret for HMAC authentication
    var DEVICE_SHARED_SECRET = "default_shared_secret_for_dev_only"

    // Sampling & timing
    const val EVENT_BATCH_SIZE = 50
    var SAMPLING_INTERVAL_MS = 10_000L      // 10 seconds
    var RECONNECT_DELAY_MS = 5_000L          // 5 seconds
    var AUTO_APPROVAL_TIMEOUT_MS = 300_000L  // 5 minutes

    // Thermal throttling thresholds
    const val THERMAL_WARN_TEMP = 40.0f      // Start reducing sampling frequency
    const val THERMAL_CRITICAL_TEMP = 45.0f  // Aggressively throttle
    const val THERMAL_SAMPLING_MULTIPLIER = 1.5f // 1.5x slower when warm
    const val THERMAL_CRITICAL_MULTIPLIER = 3.0f // 3x slower when hot

    // VPN flow capture
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
