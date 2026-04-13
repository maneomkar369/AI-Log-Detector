package com.anomalydetector

/**
 * Global configuration constants.
 * Update SERVER_URL with your NGROK WebSocket URL.
 */
object Config {
    // Edge server WebSocket URL (update with your ngrok domain)
    var SERVER_URL = "wss://your-domain.ngrok.io/ws"

    // Sampling & timing
    const val EVENT_BATCH_SIZE = 50
    const val SAMPLING_INTERVAL_MS = 10_000L      // 10 seconds
    const val RECONNECT_DELAY_MS = 5_000L          // 5 seconds
    const val AUTO_APPROVAL_TIMEOUT_MS = 300_000L  // 5 minutes

    // Notification channels
    const val CHANNEL_MONITORING = "monitoring_channel"
    const val CHANNEL_ALERTS = "alerts_channel"

    // Notification IDs
    const val NOTIFICATION_MONITORING = 1001
    const val NOTIFICATION_ALERT_BASE = 2000
}
