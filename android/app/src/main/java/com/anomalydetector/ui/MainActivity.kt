package com.anomalydetector.ui

import android.content.res.ColorStateList
import android.content.BroadcastReceiver
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.view.MotionEvent
import android.view.View
import android.view.animation.DecelerateInterpolator
import android.widget.ArrayAdapter
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.recyclerview.widget.LinearLayoutManager
import com.anomalydetector.Config
import com.anomalydetector.R
import com.anomalydetector.data.model.Alert
import com.anomalydetector.databinding.ActivityMainBinding
import com.anomalydetector.service.MonitoringService
import com.anomalydetector.service.NetworkFlowVpnService
import dagger.hilt.android.AndroidEntryPoint
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.TextStyle
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Main screen showing:
 * - Connection status indicator
 * - Start/Stop monitoring toggle
 * - Alert list (color-coded by severity)
 * - Unsynced event count
 */
@AndroidEntryPoint
class MainActivity : AppCompatActivity() {

    private enum class HomePage {
        DASHBOARD,
        PROFILES,
        CONFIG,
        SETTINGS,
    }

    private data class ProfilePreset(
        val buffer: String,
        val samplingMs: Long,
        val packageFilter: String,
        val crashDetection: Boolean,
        val mlScoring: Boolean,
        val sqliteLogging: Boolean,
        val pushNotifications: Boolean,
        val reconnectDelayMs: Long,
        val autoApprovalTimeoutMs: Long,
    )

    private data class SevenDaySeries(
        val counts: List<Int>,
        val labels: List<String>,
    )

    private lateinit var binding: ActivityMainBinding
    private val viewModel: MainViewModel by viewModels()
    private lateinit var alertAdapter: AlertAdapter
    private val uiConfigPrefs by lazy { getSharedPreferences("ui_config", MODE_PRIVATE) }
    private val settingsPrefs by lazy { getSharedPreferences("settings", MODE_PRIVATE) }
    private var currentPage: HomePage = HomePage.DASHBOARD

    private val profileCards by lazy {
        listOf(
            binding.cardProfileDev to "Development",
            binding.cardProfileSecurity to "Security Audit",
            binding.cardProfilePerformance to "Performance",
            binding.cardProfileQa to "Production QA",
        )
    }

    private val bufferOptions = listOf("all", "main", "system", "events", "radio", "crash")
    private val samplingOptions = listOf("5000 ms", "10000 ms", "15000 ms", "30000 ms")

    private val profilePresets = mapOf(
        "Development" to ProfilePreset(
            buffer = "all",
            samplingMs = 10_000L,
            packageFilter = "",
            crashDetection = true,
            mlScoring = true,
            sqliteLogging = true,
            pushNotifications = true,
            reconnectDelayMs = 5_000L,
            autoApprovalTimeoutMs = 300_000L,
        ),
        "Security Audit" to ProfilePreset(
            buffer = "all",
            samplingMs = 5_000L,
            packageFilter = "",
            crashDetection = true,
            mlScoring = true,
            sqliteLogging = true,
            pushNotifications = true,
            reconnectDelayMs = 2_000L,
            autoApprovalTimeoutMs = 120_000L,
        ),
        "Performance" to ProfilePreset(
            buffer = "main",
            samplingMs = 15_000L,
            packageFilter = "",
            crashDetection = false,
            mlScoring = false,
            sqliteLogging = true,
            pushNotifications = false,
            reconnectDelayMs = 8_000L,
            autoApprovalTimeoutMs = 600_000L,
        ),
        "Production QA" to ProfilePreset(
            buffer = "main",
            samplingMs = 10_000L,
            packageFilter = "",
            crashDetection = true,
            mlScoring = true,
            sqliteLogging = true,
            pushNotifications = true,
            reconnectDelayMs = 5_000L,
            autoApprovalTimeoutMs = 300_000L,
        ),
    )

    private val connectionStatusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: android.content.Context?, intent: Intent?) {
            if (intent?.action != MonitoringService.ACTION_CONNECTION_STATUS) return
            val status = intent.getStringExtra(MonitoringService.EXTRA_CONNECTION_STATUS)
                ?: return
            viewModel.setConnectionStatus(status)
        }
    }

    private val vpnStatusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: android.content.Context?, intent: Intent?) {
            if (intent?.action != NetworkFlowVpnService.ACTION_VPN_STATUS) return
            val status = intent.getStringExtra(NetworkFlowVpnService.EXTRA_VPN_STATUS)
                ?: "VPN flow: unknown"
            val active = intent.getBooleanExtra(NetworkFlowVpnService.EXTRA_VPN_ACTIVE, false)
            viewModel.setVpnStatus(status)
            viewModel.setVpnActive(active)
        }
    }

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            startVpnFlowService()
        } else {
            Toast.makeText(this, "VPN permission denied", Toast.LENGTH_SHORT).show()
            viewModel.setVpnStatus("VPN flow: permission denied")
            viewModel.setVpnActive(false)
        }
    }

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) {
            Toast.makeText(
                this,
                "Notification permission denied. Alerts still appear in-app.",
                Toast.LENGTH_LONG,
            ).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        requestNotificationPermissionIfNeeded()

        setupRecyclerView()
        setupNavigationTabs()
        setupProfileCards()
        setupConfigPage()
        setupObservers()
        setupClickListeners()
        setupInteractiveMotion()
        restoreLastConnectionStatus()
        restoreMonitoringPreference()
        restoreLastVpnStatus()

        showPage(HomePage.DASHBOARD, animate = false)
        setDefaultChartState()
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return
        }

        if (checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
            return
        }

        notificationPermissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
    }

    override fun onStart() {
        super.onStart()
        val filter = IntentFilter(MonitoringService.ACTION_CONNECTION_STATUS)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(connectionStatusReceiver, filter, RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(connectionStatusReceiver, filter)
        }

        val vpnFilter = IntentFilter(NetworkFlowVpnService.ACTION_VPN_STATUS)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(vpnStatusReceiver, vpnFilter, RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(vpnStatusReceiver, vpnFilter)
        }
    }

    override fun onStop() {
        try {
            unregisterReceiver(connectionStatusReceiver)
        } catch (_: IllegalArgumentException) {
        }
        try {
            unregisterReceiver(vpnStatusReceiver)
        } catch (_: IllegalArgumentException) {
        }
        super.onStop()
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
            binding.textTotalAlerts.text = alerts.size.toString()

            val pending = alerts.count { it.status.equals("pending", ignoreCase = true) }
            val approved = alerts.count { it.status.equals("approved", ignoreCase = true) }
            binding.textPendingAlerts.text = pending.toString()
            binding.textApprovedAlerts.text = approved.toString()

            updateAlertPieChart(alerts)
            updateAlertTrendChart(alerts)
        }

        viewModel.isMonitoring.observe(this) { active ->
            binding.btnToggle.text = if (active) "Stop Monitoring" else "Start Monitoring"
        }

        viewModel.connectionStatus.observe(this) { status ->
            val normalized = status.lowercase(Locale.getDefault())
            val isConnecting = normalized.contains("connecting") || normalized.contains("reconnecting")
            val isDisconnected = normalized.contains("disconnected")
            val isConnected = normalized.contains("connected") && !isDisconnected && !isConnecting

            val headerStatusColor = if (isConnected) {
                Color.parseColor("#22C55E")
            } else {
                Color.parseColor("#EF4444")
            }
            binding.textHeaderStatus.text = if (isConnected) "Live" else "Disconnected"
            binding.textHeaderStatus.setTextColor(headerStatusColor)
            binding.headerStatusDot.backgroundTintList = ColorStateList.valueOf(headerStatusColor)
        }

        viewModel.vpnStatus.observe(this) { status ->
            binding.textVpnStatus.text = status
        }

        viewModel.isVpnActive.observe(this) { active ->
            binding.btnVpnFlow.text = if (active) {
                "Stop VPN Flow Monitor"
            } else {
                "Start VPN Flow Monitor"
            }
        }
    }

    private fun setupClickListeners() {
        binding.btnToggle.setOnClickListener {
            val isActive = viewModel.isMonitoring.value ?: false
            if (isActive) {
                MonitoringService.setMonitoringEnabled(this, false)
                stopService(Intent(this, MonitoringService::class.java))
                viewModel.setMonitoring(false)
                viewModel.setConnectionStatus("Disconnected")
                Toast.makeText(this, "Monitoring stopped", Toast.LENGTH_SHORT).show()
            } else {
                MonitoringService.setMonitoringEnabled(this, true)
                startForegroundService(Intent(this, MonitoringService::class.java))
                viewModel.setMonitoring(true)
                viewModel.setConnectionStatus("Connecting...")
                Toast.makeText(this, "Monitoring started", Toast.LENGTH_SHORT).show()
            }
        }

        binding.btnSettings.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }

        binding.btnVpnFlow.setOnClickListener {
            val active = viewModel.isVpnActive.value ?: false
            if (active) {
                stopVpnFlowService()
                return@setOnClickListener
            }

            val prepareIntent = VpnService.prepare(this)
            if (prepareIntent != null) {
                vpnPermissionLauncher.launch(prepareIntent)
            } else {
                startVpnFlowService()
            }
        }

        binding.btnSaveConfig.setOnClickListener {
            saveConfigPageState()
        }
    }

    private fun setupNavigationTabs() {
        binding.tabDashboard.setOnClickListener { showPage(HomePage.DASHBOARD) }
        binding.tabProfiles.setOnClickListener { showPage(HomePage.PROFILES) }
        binding.tabConfig.setOnClickListener { showPage(HomePage.CONFIG) }
        binding.tabSettings.setOnClickListener { showPage(HomePage.SETTINGS) }
    }

    private fun showPage(page: HomePage, animate: Boolean = true) {
        if (page == currentPage && animate) {
            return
        }

        val incomingView = pageToView(page)
        val outgoingView = pageToView(currentPage)

        if (!animate || outgoingView === incomingView || !outgoingView.isVisible) {
            pageViews().forEach { view ->
                view.isVisible = view === incomingView
                view.alpha = 1f
                view.translationX = 0f
            }
        } else {
            incomingView.alpha = 0f
            incomingView.translationX = 22f
            incomingView.isVisible = true

            incomingView.animate()
                .alpha(1f)
                .translationX(0f)
                .setDuration(220)
                .setInterpolator(DecelerateInterpolator())
                .start()

            outgoingView.animate()
                .alpha(0f)
                .translationX(-18f)
                .setDuration(180)
                .withEndAction {
                    outgoingView.isVisible = false
                    outgoingView.alpha = 1f
                    outgoingView.translationX = 0f
                }
                .setInterpolator(DecelerateInterpolator())
                .start()
        }

        currentPage = page
        updateTabVisual(binding.tabDashboard, currentPage == HomePage.DASHBOARD)
        updateTabVisual(binding.tabProfiles, currentPage == HomePage.PROFILES)
        updateTabVisual(binding.tabConfig, currentPage == HomePage.CONFIG)
        updateTabVisual(binding.tabSettings, currentPage == HomePage.SETTINGS)
    }

    private fun pageViews(): List<View> {
        return listOf(
            binding.pageDashboard,
            binding.pageProfiles,
            binding.pageConfig,
            binding.pageSettings,
        )
    }

    private fun pageToView(page: HomePage): View {
        return when (page) {
            HomePage.DASHBOARD -> binding.pageDashboard
            HomePage.PROFILES -> binding.pageProfiles
            HomePage.CONFIG -> binding.pageConfig
            HomePage.SETTINGS -> binding.pageSettings
        }
    }

    private fun updateTabVisual(tab: TextView, selected: Boolean) {
        tab.setBackgroundResource(
            if (selected) R.drawable.bg_nav_tab_active
            else R.drawable.bg_nav_tab_inactive
        )
        val tint = if (selected) {
            Color.parseColor("#FFFFFF")
        } else {
            Color.parseColor("#53627E")
        }
        tab.setTextColor(tint)
        tab.alpha = if (selected) 1f else 0.9f
        tab.compoundDrawablesRelative.forEach { drawable ->
            drawable?.mutate()?.setTint(tint)
        }

        val scale = if (selected) 1.05f else 1f
        tab.animate()
            .scaleX(scale)
            .scaleY(scale)
            .setDuration(150)
            .setInterpolator(DecelerateInterpolator())
            .start()
    }

    private fun setupInteractiveMotion() {
        val pressables = listOf<View>(
            binding.tabDashboard,
            binding.tabProfiles,
            binding.tabConfig,
            binding.tabSettings,
            binding.btnToggle,
            binding.btnVpnFlow,
            binding.btnSaveConfig,
            binding.btnSettings,
            binding.cardProfileDev,
            binding.cardProfileSecurity,
            binding.cardProfilePerformance,
            binding.cardProfileQa,
        )

        pressables.forEach { view ->
            view.setOnTouchListener { v, event ->
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        v.animate()
                            .scaleX(0.98f)
                            .scaleY(0.98f)
                            .setDuration(110)
                            .setInterpolator(DecelerateInterpolator())
                            .start()
                    }

                    MotionEvent.ACTION_CANCEL,
                    MotionEvent.ACTION_UP -> {
                        v.animate()
                            .scaleX(1f)
                            .scaleY(1f)
                            .setDuration(150)
                            .setInterpolator(DecelerateInterpolator())
                            .start()
                    }
                }
                false
            }
        }
    }

    private fun setupProfileCards() {
        profileCards.forEach { (card, profileName) ->
            card.setOnClickListener {
                activateProfile(profileName, userTriggered = true)
            }
        }

        val saved = uiConfigPrefs.getString("active_profile", "Development") ?: "Development"
        activateProfile(saved, userTriggered = false)
    }

    private fun activateProfile(profileName: String, userTriggered: Boolean) {
        profileCards.forEach { (card, name) ->
            card.setBackgroundResource(
                if (name == profileName) R.drawable.bg_mirror_card_active
                else R.drawable.bg_mirror_card
            )
        }
        binding.textActiveProfile.text = "Active profile: $profileName"
        uiConfigPrefs.edit().putString("active_profile", profileName).apply()
        applyProfilePreset(profileName, userTriggered)
    }

    private fun applyProfilePreset(profileName: String, userTriggered: Boolean) {
        val preset = profilePresets[profileName] ?: return

        setSpinnerValue(binding.spinnerConfigBuffer, preset.buffer)
        setSpinnerValue(binding.spinnerConfigSampling, "${preset.samplingMs} ms")
        binding.editConfigPackageFilter.setText(preset.packageFilter)
        binding.switchConfigCrash.isChecked = preset.crashDetection
        binding.switchConfigMl.isChecked = preset.mlScoring
        binding.switchConfigSqlite.isChecked = preset.sqliteLogging
        binding.switchConfigPush.isChecked = preset.pushNotifications

        Config.SAMPLING_INTERVAL_MS = preset.samplingMs
        Config.RECONNECT_DELAY_MS = preset.reconnectDelayMs
        Config.AUTO_APPROVAL_TIMEOUT_MS = preset.autoApprovalTimeoutMs

        uiConfigPrefs.edit()
            .putString("cfg_buffer", preset.buffer)
            .putString("cfg_sampling", "${preset.samplingMs} ms")
            .putString("cfg_package_filter", preset.packageFilter)
            .putBoolean("cfg_crash", preset.crashDetection)
            .putBoolean("cfg_ml", preset.mlScoring)
            .putBoolean("cfg_sqlite", preset.sqliteLogging)
            .putBoolean("cfg_push", preset.pushNotifications)
            .apply()

        settingsPrefs.edit()
            .putLong("sampling_interval_ms", preset.samplingMs)
            .putLong("reconnect_delay_ms", preset.reconnectDelayMs)
            .putLong("auto_approval_timeout_ms", preset.autoApprovalTimeoutMs)
            .putBoolean("notifications_enabled", preset.pushNotifications)
            .putBoolean("ml_scoring_enabled", preset.mlScoring)
            .apply()

        val now = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
        binding.textConfigSaved.text = "$profileName preset applied at $now"

        if (userTriggered) {
            Toast.makeText(
                this,
                "$profileName profile applied",
                Toast.LENGTH_SHORT,
            ).show()
        }
    }

    private fun setupConfigPage() {
        binding.spinnerConfigBuffer.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            bufferOptions,
        )

        binding.spinnerConfigSampling.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            samplingOptions,
        )

        loadConfigPageState()
    }

    private fun loadConfigPageState() {
        val storedBuffer = uiConfigPrefs.getString("cfg_buffer", bufferOptions.first())
            ?: bufferOptions.first()
        val storedSampling = uiConfigPrefs.getString("cfg_sampling", samplingOptions[1])
            ?: samplingOptions[1]

        setSpinnerValue(binding.spinnerConfigBuffer, storedBuffer)
        setSpinnerValue(binding.spinnerConfigSampling, storedSampling)

        binding.editConfigPackageFilter.setText(
            uiConfigPrefs.getString("cfg_package_filter", "") ?: ""
        )
        binding.switchConfigCrash.isChecked = uiConfigPrefs.getBoolean("cfg_crash", true)
        binding.switchConfigMl.isChecked = uiConfigPrefs.getBoolean("cfg_ml", true)
        binding.switchConfigSqlite.isChecked = uiConfigPrefs.getBoolean("cfg_sqlite", true)
        binding.switchConfigPush.isChecked = uiConfigPrefs.getBoolean("cfg_push", true)
    }

    private fun saveConfigPageState() {
        val selectedSampling = binding.spinnerConfigSampling.selectedItem.toString()
        val samplingMs = samplingTextToMillis(selectedSampling)

        uiConfigPrefs.edit()
            .putString("cfg_buffer", binding.spinnerConfigBuffer.selectedItem.toString())
            .putString("cfg_sampling", selectedSampling)
            .putString("cfg_package_filter", binding.editConfigPackageFilter.text.toString().trim())
            .putBoolean("cfg_crash", binding.switchConfigCrash.isChecked)
            .putBoolean("cfg_ml", binding.switchConfigMl.isChecked)
            .putBoolean("cfg_sqlite", binding.switchConfigSqlite.isChecked)
            .putBoolean("cfg_push", binding.switchConfigPush.isChecked)
            .apply()

        Config.SAMPLING_INTERVAL_MS = samplingMs

        settingsPrefs.edit()
            .putLong("sampling_interval_ms", samplingMs)
            .putBoolean("notifications_enabled", binding.switchConfigPush.isChecked)
            .putBoolean("ml_scoring_enabled", binding.switchConfigMl.isChecked)
            .apply()

        val now = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
        binding.textConfigSaved.text = "Saved at $now"
        Toast.makeText(this, "Config saved", Toast.LENGTH_SHORT).show()
    }

    private fun setSpinnerValue(spinner: Spinner, value: String) {
        for (idx in 0 until spinner.count) {
            if (spinner.getItemAtPosition(idx).toString() == value) {
                spinner.setSelection(idx)
                break
            }
        }
    }

    private fun setDefaultChartState() {
        binding.pieAlertDistribution.setCenterText("0")
        binding.pieAlertDistribution.setSlices(
            listOf(
                MirrorPieChartView.Slice("Medium", 1f, Color.parseColor("#2563EB")),
            )
        )
        val emptySeries = buildSevenDaySeries(emptyList())
        binding.trendAlertDistribution.setPoints(emptySeries.counts.map { it.toFloat() })
        binding.trendAlertDistribution.setXAxisLabels(emptySeries.labels)
        binding.textTrendSummary.text = "7-day total: 0 · peak/day: 0"
        binding.textTrendInsight.text = "No anomalies detected this week"
        binding.textCriticalSlice.text = "0"
        binding.textHighSlice.text = "0"
        binding.textMediumSlice.text = "0"
    }

    private fun updateAlertPieChart(alerts: List<Alert>) {
        val critical = alerts.count { it.severity >= 9 }
        val high = alerts.count { it.severity in 7..8 }
        val medium = alerts.count { it.severity <= 6 }

        binding.textCriticalSlice.text = critical.toString()
        binding.textHighSlice.text = high.toString()
        binding.textMediumSlice.text = medium.toString()

        binding.pieAlertDistribution.setCenterText(alerts.size.toString())
        binding.pieAlertDistribution.setSlices(
            listOf(
                MirrorPieChartView.Slice("Critical", critical.toFloat(), Color.parseColor("#D90429")),
                MirrorPieChartView.Slice("High", high.toFloat(), Color.parseColor("#F57C00")),
                MirrorPieChartView.Slice("Medium", medium.toFloat(), Color.parseColor("#2563EB")),
            )
        )
    }

    private fun updateAlertTrendChart(alerts: List<Alert>) {
        val series = buildSevenDaySeries(alerts)
        binding.trendAlertDistribution.setPoints(series.counts.map { it.toFloat() })
        binding.trendAlertDistribution.setXAxisLabels(series.labels)

        val total = series.counts.sum()
        val peak = series.counts.maxOrNull() ?: 0
        val previousWeekTotal = buildPreviousWeekTotal(alerts)
        binding.textTrendSummary.text = "7-day total: $total · peak/day: $peak"
        binding.textTrendInsight.text = buildTrendInsight(total, previousWeekTotal)
    }

    private fun buildSevenDaySeries(alerts: List<Alert>): SevenDaySeries {
        val zoneId = ZoneId.systemDefault()
        val today = LocalDate.now(zoneId)
        val days = (6 downTo 0).map { offset ->
            today.minusDays(offset.toLong())
        }

        val counts = MutableList(7) { 0 }
        alerts.forEach { alert ->
            val alertDay = Instant.ofEpochMilli(alert.receivedAt).atZone(zoneId).toLocalDate()
            val idx = days.indexOf(alertDay)
            if (idx >= 0) {
                counts[idx] = counts[idx] + 1
            }
        }

        val labels = days.map { day ->
            day.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.ENGLISH)
        }
        return SevenDaySeries(counts = counts, labels = labels)
    }

    private fun buildPreviousWeekTotal(alerts: List<Alert>): Int {
        val zoneId = ZoneId.systemDefault()
        val today = LocalDate.now(zoneId)
        val previousWeekStart = today.minusDays(13)
        val previousWeekEnd = today.minusDays(7)

        return alerts.count { alert ->
            val alertDay = Instant.ofEpochMilli(alert.receivedAt).atZone(zoneId).toLocalDate()
            !alertDay.isBefore(previousWeekStart) && !alertDay.isAfter(previousWeekEnd)
        }
    }

    private fun buildTrendInsight(currentWeekTotal: Int, previousWeekTotal: Int): String {
        if (currentWeekTotal == 0 && previousWeekTotal == 0) {
            return "No anomalies detected this week"
        }

        if (previousWeekTotal == 0) {
            return "↑ 100% increase in anomalies this week"
        }

        val delta = currentWeekTotal - previousWeekTotal
        val pct = ((abs(delta).toFloat() / previousWeekTotal.toFloat()) * 100f).roundToInt()

        return if (delta >= 0) {
            "↑ $pct% increase in anomalies this week"
        } else {
            "↓ $pct% decrease in anomalies this week"
        }
    }

    private fun samplingTextToMillis(value: String): Long {
        return value.substringBefore(" ").toLongOrNull() ?: Config.SAMPLING_INTERVAL_MS
    }

    private fun restoreLastConnectionStatus() {
        val prefs = getSharedPreferences(MonitoringService.PREF_MONITORING, MODE_PRIVATE)
        val status = prefs.getString(MonitoringService.KEY_CONNECTION_STATUS, "Disconnected")
            ?: "Disconnected"
        viewModel.setConnectionStatus(status)
    }

    private fun restoreMonitoringPreference() {
        val monitoringEnabled = MonitoringService.isMonitoringEnabled(this)
        viewModel.setMonitoring(monitoringEnabled)

        if (monitoringEnabled) {
            startForegroundService(Intent(this, MonitoringService::class.java))
        }
    }

    private fun restoreLastVpnStatus() {
        val prefs = getSharedPreferences(NetworkFlowVpnService.PREF_VPN, MODE_PRIVATE)
        val status = prefs.getString(NetworkFlowVpnService.KEY_VPN_STATUS, "VPN flow: inactive")
            ?: "VPN flow: inactive"
        val active = prefs.getBoolean(NetworkFlowVpnService.KEY_VPN_ACTIVE, false)
        viewModel.setVpnStatus(status)
        viewModel.setVpnActive(active)
    }

    private fun startVpnFlowService() {
        val intent = Intent(this, NetworkFlowVpnService::class.java).apply {
            action = NetworkFlowVpnService.ACTION_START
        }
        startForegroundService(intent)
        viewModel.setVpnStatus("Starting VPN flow monitor...")
        viewModel.setVpnActive(true)
    }

    private fun stopVpnFlowService() {
        val intent = Intent(this, NetworkFlowVpnService::class.java).apply {
            action = NetworkFlowVpnService.ACTION_STOP
        }
        startService(intent)
        viewModel.setVpnStatus("Stopping VPN flow monitor...")
        viewModel.setVpnActive(false)
    }
}
