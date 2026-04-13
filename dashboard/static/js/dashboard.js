/**
 * Dashboard — Socket.IO Client
 * Real-time event streaming and alert management.
 */

let socket;
let isPaused = false;
let eventCount = 0;
let alertCount = 0;

// ── Socket.IO Connection ──

function initSocket() {
    socket = io();

    socket.on('connect', () => {
        document.getElementById('connection-status').className = 'status-dot online';
        document.getElementById('connection-text').textContent = 'Connected';
    });

    socket.on('disconnect', () => {
        document.getElementById('connection-status').className = 'status-dot offline';
        document.getElementById('connection-text').textContent = 'Disconnected';
    });

    socket.on('new_event', (data) => {
        if (!isPaused) addLogEntry(data);
    });

    socket.on('new_alert', (data) => {
        addAlertCard(data);
        // Flash the alerts nav link
        const alertLink = document.querySelector('a[href="/alerts"]');
        if (alertLink && !alertLink.classList.contains('active')) {
            alertLink.style.animation = 'none';
            setTimeout(() => { alertLink.style.animation = 'pulse 1s 3'; }, 10);
        }
    });
}

// ── Log Viewer ──

function initLogViewer() {
    initSocket();
    // Load recent events
    fetch('/api/dashboard/events')
        .then(r => r.json())
        .then(events => {
            events.forEach(ev => addLogEntry(ev));
        })
        .catch(() => {});
}

function addLogEntry(event) {
    const container = document.getElementById('log-container');
    if (!container) return;

    // Remove placeholder
    const placeholder = container.querySelector('.log-placeholder');
    if (placeholder) placeholder.remove();

    const entry = document.createElement('div');
    entry.className = 'log-entry';

    const time = event._received
        ? new Date(event._received).toLocaleTimeString()
        : new Date().toLocaleTimeString();

    entry.innerHTML = `
        <span class="log-time">${time}</span>
        <span class="log-device">${event.device_id || '—'}</span>
        <span class="log-type ${event.event_type || ''}">${event.event_type || event.type || '?'}</span>
        <span class="log-message">${event.package_name || ''} ${event.data ? '· ' + truncate(JSON.stringify(event.data), 80) : ''}</span>
    `;
    container.appendChild(entry);

    // Auto-scroll
    container.scrollTop = container.scrollHeight;

    // Limit DOM entries
    eventCount++;
    if (container.children.length > 500) {
        container.removeChild(container.firstChild);
    }

    updateEventCount();
}

function clearLogs() {
    const container = document.getElementById('log-container');
    if (container) {
        container.innerHTML = `
            <div class="log-placeholder">
                <span class="placeholder-icon">📡</span>
                <p>Log cleared — waiting for events...</p>
            </div>`;
    }
    eventCount = 0;
    updateEventCount();
}

function togglePause() {
    isPaused = !isPaused;
    const btn = document.getElementById('btn-pause');
    if (btn) {
        btn.textContent = isPaused ? '▶ Resume' : '⏸ Pause';
        btn.className = isPaused ? 'btn btn-success' : 'btn btn-primary';
    }
}

function updateEventCount() {
    const el = document.getElementById('event-count');
    if (el) el.textContent = `${eventCount} events`;
}

function applyFilters() {
    // Client-side filtering placeholder
}

// ── Alert Viewer ──

function initAlertViewer() {
    initSocket();
    // Load recent alerts
    fetch('/api/dashboard/alerts')
        .then(r => r.json())
        .then(alerts => {
            alerts.forEach(a => addAlertCard(a));
        })
        .catch(() => {});
}

function addAlertCard(alert) {
    const container = document.getElementById('alerts-container');
    if (!container) return;

    // Remove placeholder
    const placeholder = container.querySelector('.log-placeholder');
    if (placeholder) placeholder.remove();

    const severity = alert.severity || 0;
    let level = 'low';
    if (severity >= 9) level = 'critical';
    else if (severity >= 7) level = 'high';
    else if (severity >= 4) level = 'medium';

    const card = document.createElement('div');
    card.className = `alert-card ${level}`;
    card.id = `alert-${alert.anomalyId || alert.anomaly_id}`;

    const time = alert._received
        ? new Date(alert._received).toLocaleString()
        : new Date().toLocaleString();

    card.innerHTML = `
        <div class="alert-header">
            <span class="alert-severity ${level}">
                ${levelIcon(level)} ${alert.threatType || alert.threat_type || 'UNKNOWN'} — Severity ${severity}/10
            </span>
            <span class="alert-meta">${time}</span>
        </div>
        <div class="alert-message">${alert.message || 'No description'}</div>
        <div class="alert-details">
            <span class="alert-detail">🎯 Confidence: ${((alert.confidence || 0) * 100).toFixed(0)}%</span>
            <span class="alert-detail">📱 Device: ${alert.device_id || '—'}</span>
            <span class="alert-detail">📋 Status: <strong>${alert.status || 'pending'}</strong></span>
        </div>
        <div class="alert-actions">
            <button class="btn btn-success btn-sm" onclick="approveAlert('${alert.anomalyId || alert.anomaly_id}')">✅ Approve</button>
            <button class="btn btn-danger btn-sm" onclick="denyAlert('${alert.anomalyId || alert.anomaly_id}')">❌ Deny</button>
        </div>
    `;

    container.prepend(card);
    alertCount++;
    updateAlertCount();
}

function approveAlert(alertId) {
    fetch(`/api/alerts/${alertId}/approve`, { method: 'POST' })
        .then(() => {
            const card = document.getElementById(`alert-${alertId}`);
            if (card) {
                card.querySelector('.alert-detail:last-child strong').textContent = 'approved';
                card.querySelector('.alert-actions').innerHTML = '<span style="color: var(--accent-green);">✅ Approved</span>';
            }
        });
}

function denyAlert(alertId) {
    fetch(`/api/alerts/${alertId}/deny`, { method: 'POST' })
        .then(() => {
            const card = document.getElementById(`alert-${alertId}`);
            if (card) {
                card.querySelector('.alert-detail:last-child strong').textContent = 'denied';
                card.querySelector('.alert-actions').innerHTML = '<span style="color: var(--accent-red);">❌ Denied</span>';
            }
        });
}

function filterAlerts() {
    // Client-side severity filtering placeholder
}

function updateAlertCount() {
    const el = document.getElementById('alert-count');
    if (el) el.textContent = `${alertCount} alerts`;
}

// ── Utilities ──

function levelIcon(level) {
    return { critical: '🔴', high: '🟠', medium: '🟡', low: '🟢' }[level] || '⚪';
}

function truncate(str, max) {
    return str.length > max ? str.substring(0, max) + '…' : str;
}
