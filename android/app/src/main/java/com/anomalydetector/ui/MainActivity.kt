package com.anomalydetector.ui

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.anomalydetector.databinding.ActivityMainBinding
import com.anomalydetector.service.MonitoringService
import dagger.hilt.android.AndroidEntryPoint

/**
 * Main screen showing:
 * - Connection status indicator
 * - Start/Stop monitoring toggle
 * - Alert list (color-coded by severity)
 * - Unsynced event count
 */
@AndroidEntryPoint
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val viewModel: MainViewModel by viewModels()
    private lateinit var alertAdapter: AlertAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupRecyclerView()
        setupObservers()
        setupClickListeners()
    }

    private fun setupRecyclerView() {
        alertAdapter = AlertAdapter(
            onApprove = { viewModel.approveAlert(it.anomalyId) },
            onDeny = { viewModel.denyAlert(it.anomalyId) },
        )
        binding.recyclerAlerts.apply {
            layoutManager = LinearLayoutManager(this@MainActivity)
            adapter = alertAdapter
        }
    }

    private fun setupObservers() {
        viewModel.alerts.observe(this) { alerts ->
            alertAdapter.submitList(alerts)
            binding.textAlertCount.text = "${alerts.size} alerts"
        }

        viewModel.isMonitoring.observe(this) { active ->
            binding.btnToggle.text = if (active) "⏹ Stop Monitoring" else "▶ Start Monitoring"
            binding.statusDot.setBackgroundResource(
                if (active) android.R.drawable.presence_online
                else android.R.drawable.presence_offline
            )
        }

        viewModel.unsyncedCount.observe(this) { count ->
            binding.textSyncStatus.text = "Pending sync: $count events"
        }

        viewModel.connectionStatus.observe(this) { status ->
            binding.textConnectionStatus.text = status
        }
    }

    private fun setupClickListeners() {
        binding.btnToggle.setOnClickListener {
            val isActive = viewModel.isMonitoring.value ?: false
            if (isActive) {
                stopService(Intent(this, MonitoringService::class.java))
                viewModel.setMonitoring(false)
                Toast.makeText(this, "Monitoring stopped", Toast.LENGTH_SHORT).show()
            } else {
                startForegroundService(Intent(this, MonitoringService::class.java))
                viewModel.setMonitoring(true)
                Toast.makeText(this, "Monitoring started", Toast.LENGTH_SHORT).show()
            }
        }

        binding.btnSettings.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }
    }
}
