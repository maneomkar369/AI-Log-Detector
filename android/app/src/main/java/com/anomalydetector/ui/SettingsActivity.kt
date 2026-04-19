package com.anomalydetector.ui

import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.anomalydetector.Config
import com.anomalydetector.databinding.ActivitySettingsBinding

/**
 * Full settings page for endpoint and runtime timing configuration.
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding
    private val prefs by lazy { getSharedPreferences("settings", MODE_PRIVATE) }
    private val samplingOptions = listOf("5000", "10000", "15000", "30000")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupSamplingSpinner()
        loadValues()
        setupActions()
    }

    private fun setupSamplingSpinner() {
        binding.spinnerSamplingInterval.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            samplingOptions,
        )
    }

    private fun setupActions() {
        binding.btnBackSettings.setOnClickListener {
            finish()
        }

        binding.btnSaveSettings.setOnClickListener {
            saveValues()
        }
    }

    private fun loadValues() {
        val server = prefs.getString("server_url", Config.SERVER_URL) ?: Config.SERVER_URL
        val sampling = prefs.getLong("sampling_interval_ms", Config.SAMPLING_INTERVAL_MS)
        val reconnect = prefs.getLong("reconnect_delay_ms", Config.RECONNECT_DELAY_MS)
        val autoApproval = prefs.getLong("auto_approval_timeout_ms", Config.AUTO_APPROVAL_TIMEOUT_MS)

        binding.editServerUrl.setText(server)
        binding.editReconnectDelay.setText(reconnect.toString())
        binding.editAutoApprovalTimeout.setText(autoApproval.toString())

        setSpinnerToValue(sampling.toString())

        binding.switchEnableNotifications.isChecked = prefs.getBoolean("notifications_enabled", true)
        binding.switchEnableVpnCapture.isChecked = prefs.getBoolean("vpn_capture_enabled", Config.ENABLE_VPN_TUN_CAPTURE)
        binding.switchEnableMlScoring.isChecked = prefs.getBoolean("ml_scoring_enabled", true)

        Config.SERVER_URL = server
        Config.SAMPLING_INTERVAL_MS = sampling
        Config.RECONNECT_DELAY_MS = reconnect
        Config.AUTO_APPROVAL_TIMEOUT_MS = autoApproval
    }

    private fun saveValues() {
        val server = binding.editServerUrl.text.toString().trim()
        if (server.isBlank()) {
            binding.editServerUrl.error = "Server URL is required"
            return
        }

        val sampling = binding.spinnerSamplingInterval.selectedItem.toString().toLongOrNull()
            ?: Config.SAMPLING_INTERVAL_MS
        val reconnect = binding.editReconnectDelay.text.toString().toLongOrNull()
            ?: Config.RECONNECT_DELAY_MS
        val autoApproval = binding.editAutoApprovalTimeout.text.toString().toLongOrNull()
            ?: Config.AUTO_APPROVAL_TIMEOUT_MS

        prefs.edit()
            .putString("server_url", server)
            .putLong("sampling_interval_ms", sampling)
            .putLong("reconnect_delay_ms", reconnect)
            .putLong("auto_approval_timeout_ms", autoApproval)
            .putBoolean("notifications_enabled", binding.switchEnableNotifications.isChecked)
            .putBoolean("vpn_capture_enabled", binding.switchEnableVpnCapture.isChecked)
            .putBoolean("ml_scoring_enabled", binding.switchEnableMlScoring.isChecked)
            .apply()

        Config.SERVER_URL = server
        Config.SAMPLING_INTERVAL_MS = sampling
        Config.RECONNECT_DELAY_MS = reconnect
        Config.AUTO_APPROVAL_TIMEOUT_MS = autoApproval

        binding.textSettingsStatus.text = "Saved. Restart monitoring to apply new timing values."
        Toast.makeText(this, "Settings saved", Toast.LENGTH_SHORT).show()
    }

    private fun setSpinnerToValue(value: String) {
        for (idx in 0 until binding.spinnerSamplingInterval.count) {
            if (binding.spinnerSamplingInterval.getItemAtPosition(idx).toString() == value) {
                binding.spinnerSamplingInterval.setSelection(idx)
                return
            }
        }
        binding.spinnerSamplingInterval.setSelection(1)
    }
}
