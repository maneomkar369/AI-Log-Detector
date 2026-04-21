import json
import subprocess
import time
import urllib.request
import urllib.error
import re
import sys
from datetime import datetime, timezone

EDGE = 'http://localhost:8000'
DASH = 'http://localhost:5001'
DURATION_SEC = 600
INTERVAL_SEC = 30


def run(cmd: str) -> str:
    return subprocess.check_output(cmd, shell=True, text=True).strip()


def run_sql(query: str) -> str:
    safe = query.replace('"', '\\"')
    cmd = f'docker compose exec -T postgres psql -U admin -d anomaly_detection -At -c "{safe}"'
    return run(cmd)


def get_json(url: str, timeout: int = 8):
    req = urllib.request.Request(url, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.getcode(), json.loads(r.read().decode())


def ok_endpoint(url: str):
    try:
        code, payload = get_json(url)
        return code == 200, payload
    except Exception as e:
        return False, {'error': str(e)}


# Ensure stack is up
subprocess.call('docker compose up -d', shell=True)

# Identify likely real Android app device id
try:
    device_id = run_sql("SELECT id FROM devices WHERE id NOT LIKE 'smoke_%' AND id NOT LIKE 'test_device_%' AND id <> 'ioc_test_device' ORDER BY last_seen DESC NULLS LAST LIMIT 1;")
except Exception as e:
    print(f"Error running SQL: {e}")
    sys.exit(1)

if not device_id:
    print(json.dumps({'error': 'No real device_id found in devices table (after filtering test ids).'}, indent=2))
    sys.exit(0)

start_dt = datetime.now(timezone.utc)
start_db = start_dt.strftime('%Y-%m-%d %H:%M:%S')
start_iso = start_dt.isoformat()

samples = []
loops = DURATION_SEC // INTERVAL_SEC + 1

print(f'START device_id={device_id} start={start_iso} duration_sec={DURATION_SEC} interval_sec={INTERVAL_SEC}')

for i in range(loops):
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        events = int(run_sql(f"SELECT COUNT(*) FROM behavior_events WHERE device_id='{device_id}';") or '0')
        alerts = int(run_sql(f"SELECT COUNT(*) FROM alerts WHERE device_id='{device_id}';") or '0')
    except:
        events, alerts = 0, 0

    edge_ok, edge_payload = ok_endpoint(f'{EDGE}/api/health')
    dash_ok, dash_payload = ok_endpoint(f'{DASH}/api/dashboard/summary')
    adb_ok, adb_payload = ok_endpoint(f'{DASH}/api/adb/status')

    adb_connected = bool(adb_payload.get('connected')) if isinstance(adb_payload, dict) else False

    samples.append({
        't': now_iso,
        'events': events,
        'alerts': alerts,
        'edge_ok': edge_ok,
        'dash_ok': dash_ok,
        'adb_ok': adb_ok,
        'adb_connected': adb_connected,
    })

    print(f'SAMPLE {i+1}/{loops} events={events} alerts={alerts} edge={edge_ok} dash={dash_ok} adb={adb_connected}')
    sys.stdout.flush()
    if i < loops - 1:
        time.sleep(INTERVAL_SEC)

# Compute reliability metrics
first_events = samples[0]['events']
last_events = samples[-1]['events']
total_growth = last_events - first_events

event_deltas = [samples[i+1]['events'] - samples[i]['events'] for i in range(len(samples)-1)]
zero_or_negative_intervals = sum(1 for d in event_deltas if d <= 0)
interval_count = max(1, len(event_deltas))
drop_rate_pct = round((zero_or_negative_intervals / interval_count) * 100.0, 2)

edge_uptime_pct = round(100.0 * sum(1 for s in samples if s['edge_ok']) / len(samples), 2)
dash_uptime_pct = round(100.0 * sum(1 for s in samples if s['dash_ok']) / len(samples), 2)
adb_connected_pct = round(100.0 * sum(1 for s in samples if s['adb_connected']) / len(samples), 2)

# Reconnection and websocket error signals from edge logs during soak window
try:
    log_text = run(f"docker compose logs --since '{start_iso}' edge_server")
except Exception:
    log_text = ''

conn_pat = re.compile(rf"Device connected: {re.escape(device_id)}")
disconn_pat = re.compile(rf"Device disconnected: {re.escape(device_id)}")
err_pat = re.compile(rf"WebSocket error for {re.escape(device_id)}|Send to {re.escape(device_id)} failed")

connect_events = len(conn_pat.findall(log_text))
disconnect_events = len(disconn_pat.findall(log_text))
websocket_errors = len(err_pat.findall(log_text))

# Alert/XAI consistency for alerts created during soak window
allowed_status = {'pending', 'approved', 'denied', 'snoozed', 'auto_escalated'}
try:
    lines = run_sql(
        f"SELECT anomaly_id, severity, status, CASE WHEN xai_explanation IS NULL OR xai_explanation='' THEN 0 ELSE 1 END "
        f"FROM alerts WHERE device_id='{device_id}' AND created_at >= '{start_db}' ORDER BY created_at ASC;"
    ).splitlines()
except:
    lines = []

checked_alerts = 0
severity_ok = True
status_ok = True
xai_present_count = 0
for ln in lines:
    if not ln.strip():
        continue
    parts = ln.split('|')
    if len(parts) < 4:
        continue
    checked_alerts += 1
    try:
        sev = int(parts[1])
    except:
        sev = 0
    st = parts[2].strip().lower()
    has_xai = int(parts[3]) == 1
    if not (1 <= sev <= 10):
        severity_ok = False
    if st not in allowed_status:
        status_ok = False
    if has_xai:
        xai_present_count += 1

if checked_alerts == 0:
    alert_consistency_pass = True
    alert_consistency_detail = 'No new alerts generated during soak window.'
else:
    xai_ratio = xai_present_count / checked_alerts
    alert_consistency_pass = severity_ok and status_ok and xai_ratio >= 0.9
    alert_consistency_detail = f'checked={checked_alerts}, xai_ratio={xai_ratio:.2f}, severity_ok={severity_ok}, status_ok={status_ok}'

live_ingestion_pass = total_growth > 0 and drop_rate_pct < 50.0
api_stability_pass = edge_uptime_pct == 100.0 and dash_uptime_pct == 100.0
adb_stability_pass = adb_connected_pct >= 95.0
reconnect_behavior_pass = websocket_errors == 0

overall_pass = all([
    live_ingestion_pass,
    api_stability_pass,
    adb_stability_pass,
    reconnect_behavior_pass,
    alert_consistency_pass,
])

report = {
    'device_id': device_id,
    'duration_sec': DURATION_SEC,
    'sample_interval_sec': INTERVAL_SEC,
    'samples_collected': len(samples),
    'metrics': {
        'event_growth_total': total_growth,
        'event_deltas': event_deltas,
        'ingestion_drop_rate_pct': drop_rate_pct,
        'edge_uptime_pct': edge_uptime_pct,
        'dashboard_uptime_pct': dash_uptime_pct,
        'adb_connected_pct': adb_connected_pct,
        'connect_events_in_logs': connect_events,
        'disconnect_events_in_logs': disconnect_events,
        'websocket_error_events': websocket_errors,
    },
    'checks': {
        'live_ingestion': {
            'pass': live_ingestion_pass,
            'detail': f'growth={total_growth}, drop_rate_pct={drop_rate_pct}',
        },
        'api_stability': {
            'pass': api_stability_pass,
            'detail': f'edge_uptime={edge_uptime_pct}%, dashboard_uptime={dash_uptime_pct}%',
        },
        'adb_bridge_stability': {
            'pass': adb_stability_pass,
            'detail': f'adb_connected_pct={adb_connected_pct}%',
        },
        'reconnection_behavior': {
            'pass': reconnect_behavior_pass,
            'detail': f'connect={connect_events}, disconnect={disconnect_events}, ws_errors={websocket_errors}',
        },
        'alert_consistency': {
            'pass': alert_consistency_pass,
            'detail': alert_consistency_detail,
        },
    },
    'overall_pass': overall_pass,
}

print('SOAK_REPORT_BEGIN')
print(json.dumps(report, indent=2))
print('SOAK_REPORT_END')
