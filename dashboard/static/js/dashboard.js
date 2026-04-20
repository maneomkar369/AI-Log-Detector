const dashboardState = {
    initialized: false,
    socket: null,
    summaryRefreshTimer: null,
    trendChart: null,
    distributionChart: null,
    activeProfile: "Development",
    logsPaused: false,
    adbRowCount: 0,
    maxAdbRows: 650,
    recentEventRows: [],
    recentEventFilter: "all",
};

const PROFILE_PRESETS = {
    Development: {
        detect_crash: true,
        auth_threshold: "8",
        detect_cleartext_network: false,
        memory_anomaly_level: "medium",
        sqlite_logging: true,
        ml_scoring: true,
        export_format: "json",
    },
    "Security Audit": {
        detect_crash: true,
        auth_threshold: "3",
        detect_cleartext_network: true,
        memory_anomaly_level: "high",
        sqlite_logging: true,
        ml_scoring: true,
        export_format: "json",
    },
    Performance: {
        detect_crash: false,
        auth_threshold: "12",
        detect_cleartext_network: false,
        memory_anomaly_level: "high",
        sqlite_logging: true,
        ml_scoring: false,
        export_format: "csv",
    },
    "Production QA": {
        detect_crash: true,
        auth_threshold: "5",
        detect_cleartext_network: true,
        memory_anomaly_level: "medium",
        sqlite_logging: true,
        ml_scoring: true,
        export_format: "parquet",
    },
};

function initDashboardExperience() {
    if (dashboardState.initialized) {
        return;
    }
    dashboardState.initialized = true;

    initSocket();
    initCharts();
    bindLogControls();
    bindAdbConfigForm();
    bindProfileCards();
    bindSettingsForm();
    bindRecentEventFilters();
    bindIocMetricCards();

    void loadInitialData();
    window.setInterval(refreshSummary, 10000);
    window.setInterval(refreshAdbStatus, 4000);
}

function initSocket() {
    if (dashboardState.socket) {
        return;
    }

    const socket = io();
    dashboardState.socket = socket;

    socket.on("connect", () => {
        updateSocketStatus(true, "Socket connected");
    });

    socket.on("disconnect", () => {
        updateSocketStatus(false, "Socket disconnected");
    });

    socket.on("new_event", () => {
        scheduleSummaryRefresh();
    });

    socket.on("new_alert", () => {
        scheduleSummaryRefresh();
    });

    socket.on("adb_log", (entry) => {
        if (dashboardState.logsPaused) {
            return;
        }
        addAdbLogRow(entry);
    });

    socket.on("adb_status", (payload) => {
        renderAdbStatus(payload);
    });
}

function updateSocketStatus(connected, text) {
    const dot = document.getElementById("socket-status-dot");
    const label = document.getElementById("socket-status-text");
    if (dot) {
        dot.className = connected ? "status-dot online" : "status-dot offline";
    }
    if (label) {
        label.textContent = text;
    }
}

function scheduleSummaryRefresh() {
    if (dashboardState.summaryRefreshTimer) {
        window.clearTimeout(dashboardState.summaryRefreshTimer);
    }
    dashboardState.summaryRefreshTimer = window.setTimeout(() => {
        void refreshSummary();
    }, 450);
}

async function loadInitialData() {
    await Promise.all([
        refreshSummary(),
        refreshAdbStatus(),
        loadRecentAdbLogs(),
        loadSettings(),
    ]);
}

async function refreshSummary() {
    const payload = await fetchJSON("/api/dashboard/summary");
    if (!payload) {
        return;
    }

    renderMetrics(payload.metrics || {});
    renderTrendChart(payload.trend || {});
    renderDistributionChart(payload.today_distribution || {});
    renderRecentEvents(payload.recent_events || []);

    const updated = document.getElementById("summary-updated");
    if (updated) {
        updated.textContent = formatTime(new Date().toISOString());
    }
}

function renderMetrics(metrics) {
    setText("metric-total-anomalies", String(metrics.total_anomalies || 0));
    setText("metric-critical-alerts", String(metrics.critical_alerts || 0));
    setText("metric-network-events", String(metrics.network_events || 0));
    setText("metric-auth-failures", String(metrics.auth_failures || 0));
    setText("metric-ioc-alerts", String(metrics.ioc_alerts || 0));
    setText("metric-ioc-app-alerts", String(metrics.ioc_app_alerts || 0));
    setText("metric-ioc-domain-alerts", String(metrics.ioc_domain_alerts || 0));
}

function initCharts() {
    const trendCanvas = document.getElementById("trend-chart");
    if (trendCanvas && window.Chart) {
        dashboardState.trendChart = new Chart(trendCanvas, {
            type: "line",
            data: {
                labels: [],
                datasets: [
                    {
                        label: "Anomalies",
                        data: [],
                        borderColor: "#4bd4ff",
                        backgroundColor: "rgba(75, 212, 255, 0.18)",
                        tension: 0.3,
                        fill: true,
                    },
                    {
                        label: "Critical",
                        data: [],
                        borderColor: "#f56767",
                        backgroundColor: "rgba(245, 103, 103, 0.16)",
                        tension: 0.3,
                    },
                    {
                        label: "Network",
                        data: [],
                        borderColor: "#31f0be",
                        backgroundColor: "rgba(49, 240, 190, 0.14)",
                        tension: 0.3,
                    },
                    {
                        label: "Auth Failures",
                        data: [],
                        borderColor: "#f4b740",
                        backgroundColor: "rgba(244, 183, 64, 0.14)",
                        tension: 0.3,
                    },
                ],
            },
            options: chartSharedOptions(),
        });
    }

    const distCanvas = document.getElementById("distribution-chart");
    if (distCanvas && window.Chart) {
        dashboardState.distributionChart = new Chart(distCanvas, {
            type: "doughnut",
            data: {
                labels: ["Anomalies", "Critical", "Network", "Auth Failures"],
                datasets: [
                    {
                        data: [0, 0, 0, 0],
                        backgroundColor: ["#4bd4ff", "#f56767", "#31f0be", "#f4b740"],
                        borderColor: "rgba(9, 17, 25, 0.9)",
                        borderWidth: 2,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: {
                            color: "#ebf6ff",
                            boxWidth: 12,
                        },
                    },
                },
            },
        });
    }
}

function chartSharedOptions() {
    return {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
            mode: "index",
            intersect: false,
        },
        scales: {
            x: {
                ticks: {
                    color: "#9cc2dc",
                },
                grid: {
                    color: "rgba(146, 181, 204, 0.12)",
                },
            },
            y: {
                beginAtZero: true,
                ticks: {
                    color: "#9cc2dc",
                    precision: 0,
                },
                grid: {
                    color: "rgba(146, 181, 204, 0.12)",
                },
            },
        },
        plugins: {
            legend: {
                labels: {
                    color: "#ebf6ff",
                },
            },
        },
    };
}

function renderTrendChart(trend) {
    if (!dashboardState.trendChart) {
        return;
    }

    dashboardState.trendChart.data.labels = trend.labels || [];
    dashboardState.trendChart.data.datasets[0].data = trend.anomalies || [];
    dashboardState.trendChart.data.datasets[1].data = trend.critical || [];
    dashboardState.trendChart.data.datasets[2].data = trend.network || [];
    dashboardState.trendChart.data.datasets[3].data = trend.auth_failures || [];
    dashboardState.trendChart.update();
}

function renderDistributionChart(distribution) {
    if (!dashboardState.distributionChart) {
        return;
    }

    dashboardState.distributionChart.data.datasets[0].data = [
        distribution.anomalies || 0,
        distribution.critical || 0,
        distribution.network || 0,
        distribution.auth_failures || 0,
    ];
    dashboardState.distributionChart.update();
}

function renderRecentEvents(rows) {
    dashboardState.recentEventRows = Array.isArray(rows) ? rows : [];
    applyRecentEventFilter();
}

function bindRecentEventFilters() {
    const select = document.getElementById("recent-events-filter");
    if (!select) {
        return;
    }

    select.addEventListener("change", () => {
        setRecentEventFilter(select.value || "all");
    });
}

function bindIocMetricCards() {
    const cards = document.querySelectorAll(".metric-filter-card[data-filter-mode]");
    cards.forEach((card) => {
        const mode = card.getAttribute("data-filter-mode") || "all";
        card.addEventListener("click", () => {
            setRecentEventFilter(mode);
        });

        card.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                setRecentEventFilter(mode);
            }
        });
    });

    syncIocMetricCardState();
}

function setRecentEventFilter(mode) {
    dashboardState.recentEventFilter = mode || "all";

    const select = document.getElementById("recent-events-filter");
    if (select && select.value !== dashboardState.recentEventFilter) {
        select.value = dashboardState.recentEventFilter;
    }

    applyRecentEventFilter();
    syncIocMetricCardState();
}

function syncIocMetricCardState() {
    const cards = document.querySelectorAll(".metric-filter-card[data-filter-mode]");
    cards.forEach((card) => {
        const mode = card.getAttribute("data-filter-mode") || "";
        const isActive = mode === dashboardState.recentEventFilter;
        card.classList.toggle("is-active", isActive);
        card.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
}

function applyRecentEventFilter() {
    const tbody = document.getElementById("recent-events-body");
    if (!tbody) {
        return;
    }

    const rows = dashboardState.recentEventRows;
    const mode = dashboardState.recentEventFilter;
    const filteredRows = rows.filter((row) => {
        const iocType = normalizeIocType(row.ioc_type || classifyIocFromRow(row));

        if (mode === "ioc") {
            return iocType === "app" || iocType === "domain";
        }
        if (mode === "ioc-app") {
            return iocType === "app";
        }
        if (mode === "ioc-domain") {
            return iocType === "domain";
        }
        return true;
    });

    tbody.innerHTML = "";
    if (!filteredRows.length) {
        const message = rows.length
            ? "No rows match the selected filter."
            : "No events available yet.";
        tbody.innerHTML = `<tr><td colspan="7" class="empty-row">${escapeHtml(message)}</td></tr>`;
        return;
    }

    filteredRows.forEach((row) => {
        const tr = document.createElement("tr");
        const severity = (row.severity || "low").toLowerCase();
        const iocType = normalizeIocType(row.ioc_type || classifyIocFromRow(row));
        tr.innerHTML = `
            <td>${escapeHtml(formatDateTime(row.time))}</td>
            <td>${escapeHtml(row.device_id || "-")}</td>
            <td>${escapeHtml(row.source || "-")}</td>
            <td>${escapeHtml(row.event_type || "-")}</td>
            <td><span class="severity-badge severity-${escapeHtml(severity)}">${escapeHtml(severity)}</span></td>
            <td>${renderIocBadge(iocType)}</td>
            <td>${escapeHtml(row.message || "-")}</td>
        `;
        tbody.appendChild(tr);
    });
}

function normalizeIocType(rawValue) {
    const token = String(rawValue || "none").toLowerCase();
    if (token === "app" || token === "domain") {
        return token;
    }
    return "none";
}

function classifyIocFromRow(row) {
    if (!row || String(row.source || "").toUpperCase() !== "ALERT") {
        return "none";
    }

    const message = String(row.message || "").toLowerCase();
    if (message.includes("known malicious app activity detected")) {
        return "app";
    }
    if (message.includes("known malicious website detected")) {
        return "domain";
    }
    return "none";
}

function renderIocBadge(iocType) {
    if (iocType === "app") {
        return '<span class="ioc-badge ioc-app">App IOC</span>';
    }
    if (iocType === "domain") {
        return '<span class="ioc-badge ioc-domain">Domain IOC</span>';
    }
    return '<span class="ioc-badge ioc-none">--</span>';
}

function bindLogControls() {
    const pauseButton = document.getElementById("btn-pause-logs");
    if (pauseButton) {
        pauseButton.addEventListener("click", () => {
            dashboardState.logsPaused = !dashboardState.logsPaused;
            pauseButton.textContent = dashboardState.logsPaused ? "Resume Stream" : "Pause Stream";
            pauseButton.className = dashboardState.logsPaused ? "btn btn-primary" : "btn btn-secondary";
        });
    }

    const clearButton = document.getElementById("btn-clear-logs");
    if (clearButton) {
        clearButton.addEventListener("click", () => {
            clearAdbLogs();
        });
    }
}

async function loadRecentAdbLogs() {
    const logs = await fetchJSON("/api/adb/logs?limit=260");
    clearAdbLogs();
    if (!Array.isArray(logs)) {
        return;
    }
    logs.forEach((entry) => {
        addAdbLogRow(entry, false);
    });
}

function clearAdbLogs() {
    const tbody = document.getElementById("adb-log-body");
    if (!tbody) {
        return;
    }
    tbody.innerHTML = '<tr><td colspan="6" class="empty-row">Waiting for adb logcat stream...</td></tr>';
    dashboardState.adbRowCount = 0;
    setText("adb-log-count", "0 lines");
}

function addAdbLogRow(entry, withAnimation = true) {
    const tbody = document.getElementById("adb-log-body");
    if (!tbody || !entry) {
        return;
    }

    if (tbody.querySelector(".empty-row")) {
        tbody.innerHTML = "";
    }

    const tr = document.createElement("tr");
    const severityInfo = normalizeLogSeverity(entry.severity);
    tr.innerHTML = `
        <td>${escapeHtml(formatTime(entry.timestamp))}</td>
        <td>${escapeHtml(entry.buffer || "all")}</td>
        <td>${escapeHtml(entry.pid == null ? "-" : String(entry.pid))}</td>
        <td>${escapeHtml(entry.tag || "-")}</td>
        <td><span class="severity-badge severity-${escapeHtml(severityInfo.badge)}">${escapeHtml(severityInfo.label)}</span></td>
        <td>${escapeHtml(entry.message || "")}</td>
    `;

    if (withAnimation) {
        tr.classList.add("row-animate");
    }

    tbody.appendChild(tr);
    dashboardState.adbRowCount += 1;

    while (tbody.rows.length > dashboardState.maxAdbRows) {
        tbody.deleteRow(0);
    }

    setText("adb-log-count", `${tbody.rows.length} lines`);
    const tableWrap = tbody.closest(".table-wrap");
    if (tableWrap) {
        tableWrap.scrollTop = tableWrap.scrollHeight;
    }
}

function normalizeLogSeverity(rawSeverity) {
    const token = String(rawSeverity || "I").trim().toUpperCase();
    const map = {
        V: { label: "Verbose", badge: "low" },
        D: { label: "Debug", badge: "low" },
        I: { label: "Info", badge: "medium" },
        W: { label: "Warn", badge: "medium" },
        E: { label: "Error", badge: "high" },
        F: { label: "Fatal", badge: "critical" },
        A: { label: "Assert", badge: "critical" },
    };
    return map[token] || { label: token, badge: "low" };
}

async function refreshAdbStatus() {
    const payload = await fetchJSON("/api/adb/status");
    if (!payload) {
        return;
    }
    renderAdbStatus(payload);
}

function renderAdbStatus(payload) {
    if (!payload) {
        return;
    }

    const connected = Boolean(payload.connected);
    const dot = document.getElementById("adb-connection-dot");
    if (dot) {
        dot.className = connected ? "pulse-dot online" : "pulse-dot offline";
    }

    setText("adb-connection-state", payload.state || (connected ? "connected" : "disconnected"));
    setText("adb-connection-message", payload.message || "No status message");
    setText("adb-last-updated", formatDateTime(payload.last_updated));

    const commandList = document.getElementById("adb-command-list");
    if (commandList) {
        const commands = Array.isArray(payload.commands) ? payload.commands : [];
        commandList.textContent = commands.length ? commands.join("\n") : "No adb command captured yet.";
    }

    const config = payload.config || {};
    const bufferSelect = document.getElementById("adb-buffer");
    const bufferSizeInput = document.getElementById("adb-buffer-size");
    const pollInput = document.getElementById("adb-poll-interval");
    const packageInput = document.getElementById("adb-package-filter");

    if (bufferSelect && config.buffer) {
        bufferSelect.value = config.buffer;
    }
    if (bufferSizeInput && config.buffer_size_kb != null) {
        bufferSizeInput.value = String(config.buffer_size_kb);
    }
    if (pollInput && config.poll_interval_ms != null) {
        pollInput.value = String(config.poll_interval_ms);
    }
    if (packageInput && config.package_filter != null) {
        packageInput.value = String(config.package_filter);
    }
}

function bindAdbConfigForm() {
    const form = document.getElementById("adb-config-form");
    if (!form) {
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = {
            buffer: getValue("adb-buffer"),
            buffer_size_kb: toInteger(getValue("adb-buffer-size"), 256),
            poll_interval_ms: toInteger(getValue("adb-poll-interval"), 400),
            package_filter: getValue("adb-package-filter"),
        };

        const feedback = document.getElementById("adb-config-feedback");
        if (feedback) {
            feedback.textContent = "Applying...";
        }

        const updated = await postJSON("/api/adb/config", payload);
        if (updated) {
            renderAdbStatus(updated);
            if (feedback) {
                feedback.textContent = "ADB config applied";
            }
        } else if (feedback) {
            feedback.textContent = "Failed to apply ADB config";
        }
    });
}

function bindProfileCards() {
    const cards = document.querySelectorAll(".profile-card[data-profile]");
    cards.forEach((card) => {
        card.addEventListener("click", async () => {
            const profileName = card.getAttribute("data-profile") || "Development";
            await activateProfile(profileName, true, true);
        });
    });
}

async function activateProfile(profileName, syncServer, applyPreset) {
    dashboardState.activeProfile = profileName;

    const cards = document.querySelectorAll(".profile-card[data-profile]");
    cards.forEach((card) => {
        const isActive = card.getAttribute("data-profile") === profileName;
        card.classList.toggle("active", isActive);
    });

    setText("active-profile-label", profileName);

    if (applyPreset && PROFILE_PRESETS[profileName]) {
        applySettingsToForm(PROFILE_PRESETS[profileName]);
        setText("settings-feedback", "Preset loaded. Save settings to persist.");
    }

    if (syncServer) {
        await postJSON("/api/dashboard/profile", { name: profileName });
    }
}

function bindSettingsForm() {
    const form = document.getElementById("settings-form");
    if (!form) {
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = collectSettingsFromForm();
        const feedback = document.getElementById("settings-feedback");
        if (feedback) {
            feedback.textContent = "Saving...";
        }

        const response = await postJSON("/api/dashboard/settings", payload);
        if (response) {
            if (feedback) {
                feedback.textContent = "Settings saved";
            }
        } else if (feedback) {
            feedback.textContent = "Failed to save settings";
        }
    });
}

async function loadSettings() {
    const payload = await fetchJSON("/api/dashboard/settings");
    if (!payload) {
        await activateProfile("Development", false, false);
        applySettingsToForm(PROFILE_PRESETS.Development);
        return;
    }

    applySettingsToForm(payload.settings || {});
    await activateProfile(payload.active_profile || "Development", false, false);
}

function collectSettingsFromForm() {
    return {
        detect_crash: Boolean(document.getElementById("setting-detect-crash")?.checked),
        auth_threshold: getValue("setting-auth-threshold") || "5",
        detect_cleartext_network: Boolean(document.getElementById("setting-cleartext-network")?.checked),
        memory_anomaly_level: getValue("setting-memory-anomaly") || "medium",
        sqlite_logging: Boolean(document.getElementById("setting-sqlite-logging")?.checked),
        ml_scoring: Boolean(document.getElementById("setting-ml-scoring")?.checked),
        export_format: getValue("setting-export-format") || "json",
    };
}

function applySettingsToForm(settings) {
    setChecked("setting-detect-crash", settings.detect_crash);
    setValue("setting-auth-threshold", settings.auth_threshold || "5");
    setChecked("setting-cleartext-network", settings.detect_cleartext_network);
    setValue("setting-memory-anomaly", settings.memory_anomaly_level || "medium");
    setChecked("setting-sqlite-logging", settings.sqlite_logging);
    setChecked("setting-ml-scoring", settings.ml_scoring);
    setValue("setting-export-format", settings.export_format || "json");
}

async function fetchJSON(url) {
    try {
        const response = await fetch(url, { method: "GET" });
        if (!response.ok) {
            return null;
        }
        return await response.json();
    } catch (_) {
        return null;
    }
}

async function postJSON(url, payload) {
    try {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            return null;
        }
        return await response.json();
    } catch (_) {
        return null;
    }
}

function setText(elementId, value) {
    const element = document.getElementById(elementId);
    if (element) {
        element.textContent = value;
    }
}

function setValue(elementId, value) {
    const element = document.getElementById(elementId);
    if (element) {
        element.value = String(value);
    }
}

function setChecked(elementId, value) {
    const element = document.getElementById(elementId);
    if (element) {
        element.checked = Boolean(value);
    }
}

function getValue(elementId) {
    const element = document.getElementById(elementId);
    return element ? element.value : "";
}

function toInteger(value, fallback) {
    const parsed = Number.parseInt(String(value), 10);
    if (Number.isNaN(parsed)) {
        return fallback;
    }
    return parsed;
}

function formatTime(isoString) {
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) {
        return "--";
    }
    return date.toLocaleTimeString();
}

function formatDateTime(isoString) {
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) {
        return "--";
    }
    return date.toLocaleString();
}

function escapeHtml(value) {
    const source = String(value ?? "");
    return source
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

document.addEventListener("DOMContentLoaded", () => {
    initDashboardExperience();
});
