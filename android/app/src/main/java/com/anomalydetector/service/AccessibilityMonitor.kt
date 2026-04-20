package com.anomalydetector.service

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import com.anomalydetector.data.local.AppDatabase
import com.anomalydetector.data.model.BehaviorEvent
import com.google.gson.Gson
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import javax.inject.Inject

/**
 * Accessibility service that captures keystroke timing and touch events
 * for building the user's interaction behavioral profile.
 *
 * Captured data is aggregated (timing stats only, NOT actual content)
 * to protect user privacy.
 */
@AndroidEntryPoint
class AccessibilityMonitor : AccessibilityService() {

    @Inject lateinit var database: AppDatabase

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val gson = Gson()

    // Keystroke timing
    private var lastKeystrokeTime = 0L
    private val keystrokeIntervals = mutableListOf<Long>()

    // Touch timing
    private var lastTouchTime = 0L

    // Browser-domain telemetry (host only) for malicious website detection.
    private val browserPackages = setOf(
        "com.android.chrome",
        "org.mozilla.firefox",
        "com.microsoft.emmx",
        "com.opera.browser",
        "com.brave.browser",
        "com.sec.android.app.sbrowser",
    )
    private val recentDomainSeenAt = mutableMapOf<String, Long>()

    override fun onServiceConnected() {
        val info = AccessibilityServiceInfo().apply {
            eventTypes = AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED or
                         AccessibilityEvent.TYPE_VIEW_CLICKED or
                         AccessibilityEvent.TYPE_VIEW_SCROLLED
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            notificationTimeout = 100
            flags = AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS
        }
        serviceInfo = info
        Log.i(TAG, "Accessibility monitor connected")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        event ?: return

        when (event.eventType) {
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> handleKeystroke(event)
            AccessibilityEvent.TYPE_VIEW_CLICKED -> handleTouch(event)
            AccessibilityEvent.TYPE_VIEW_SCROLLED -> handleSwipe(event)
        }
    }

    override fun onInterrupt() {
        Log.w(TAG, "Accessibility service interrupted")
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun handleKeystroke(event: AccessibilityEvent) {
        val now = System.currentTimeMillis()
        maybeCaptureWebDomain(event, now)

        if (lastKeystrokeTime > 0) {
            val interval = now - lastKeystrokeTime
            if (interval in 10..5000) {  // Filter noise
                keystrokeIntervals.add(interval)
            }
        }
        lastKeystrokeTime = now

        // Batch save every 20 keystrokes
        if (keystrokeIntervals.size >= 20) {
            val intervals = keystrokeIntervals.toList()
            keystrokeIntervals.clear()

            scope.launch {
                database.behaviorEventDao().insert(BehaviorEvent(
                    eventType = "KEYSTROKE",
                    packageName = event.packageName?.toString(),
                    timestamp = now,
                    data = gson.toJson(mapOf(
                        "latency" to intervals.average(),
                        "std" to standardDeviation(intervals),
                        "count" to intervals.size
                    ))
                ))
            }
        }
    }

    private fun maybeCaptureWebDomain(event: AccessibilityEvent, now: Long) {
        val packageName = event.packageName?.toString() ?: return
        if (packageName !in browserPackages) {
            return
        }

        val textCandidates = mutableListOf<String>()
        event.text?.forEach { textCandidates.add(it.toString()) }
        event.contentDescription?.toString()?.let { textCandidates.add(it) }

        val domain = textCandidates
            .asSequence()
            .mapNotNull { extractDomain(it) }
            .firstOrNull()
            ?: return

        val lastSeenAt = recentDomainSeenAt[domain] ?: 0L
        if (now - lastSeenAt < 60_000L) {
            return
        }
        recentDomainSeenAt[domain] = now

        scope.launch {
            database.behaviorEventDao().insert(
                BehaviorEvent(
                    eventType = "WEB_DOMAIN",
                    packageName = packageName,
                    timestamp = now,
                    data = gson.toJson(
                        mapOf(
                            "domain" to domain,
                            "source" to "accessibility",
                        )
                    )
                )
            )
        }
    }

    private fun extractDomain(raw: String): String? {
        val value = raw.trim().lowercase()
        if (value.isBlank()) {
            return null
        }

        val withoutScheme = value
            .removePrefix("https://")
            .removePrefix("http://")
        val host = withoutScheme
            .substringBefore('/')
            .substringBefore(':')
            .removePrefix("www.")
            .trim('.')

        if (host.isBlank()) {
            return null
        }

        val domainRegex = Regex("^[a-z0-9][a-z0-9.-]*\\.[a-z]{2,}$")
        return if (domainRegex.matches(host)) host else null
    }

    private fun handleTouch(event: AccessibilityEvent) {
        val now = System.currentTimeMillis()
        val duration = if (lastTouchTime > 0) now - lastTouchTime else 0
        lastTouchTime = now

        if (duration in 10..10000) {
            scope.launch {
                database.behaviorEventDao().insert(BehaviorEvent(
                    eventType = "TOUCH",
                    packageName = event.packageName?.toString(),
                    timestamp = now,
                    data = gson.toJson(mapOf("duration" to duration))
                ))
            }
        }
    }

    private fun handleSwipe(event: AccessibilityEvent) {
        scope.launch {
            database.behaviorEventDao().insert(BehaviorEvent(
                eventType = "SWIPE",
                packageName = event.packageName?.toString(),
                timestamp = System.currentTimeMillis(),
                data = gson.toJson(mapOf("scrollDelta" to (event.scrollDeltaY ?: 0)))
            ))
        }
    }

    private fun standardDeviation(values: List<Long>): Double {
        if (values.size < 2) return 0.0
        val mean = values.average()
        return Math.sqrt(values.sumOf { (it - mean) * (it - mean) } / values.size)
    }

    companion object {
        private const val TAG = "AccessibilityMonitor"
    }
}
