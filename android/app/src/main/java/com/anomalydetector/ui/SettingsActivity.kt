package com.anomalydetector.ui

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.anomalydetector.Config

/**
 * Settings screen for configuring the edge server URL,
 * sampling rate, and auto-approval timeout.
 */
class SettingsActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Simple settings using SharedPreferences
        // In production, use PreferenceFragmentCompat
        val prefs = getSharedPreferences("settings", MODE_PRIVATE)

        // Load current values
        Config.SERVER_URL = prefs.getString("server_url", Config.SERVER_URL) ?: Config.SERVER_URL

        Toast.makeText(this, "Settings: ${Config.SERVER_URL}", Toast.LENGTH_SHORT).show()

        // TODO: Build proper settings UI with:
        // - Server URL input
        // - Sampling interval slider
        // - Auto-approval timeout config
        // - Permission status checks
    }
}
