package com.anomalydetector.services

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent

class BehavioralAccessibilityService : AccessibilityService() {
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
    }

    override fun onInterrupt() {
    }
}
