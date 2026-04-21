import subprocess
import urllib.request
import json
import time

def run_psql(query):
    cmd = ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "admin", "-d", "anomaly_detection", "-t", "-c", query]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip()

def get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        return f"Error: {e}"

def main():
    print("--- 1. Selecting Device ---")
    query = "SELECT device_id FROM behavior_events WHERE device_id NOT LIKE 'smoke_%' AND device_id NOT LIKE 'test_device_%' AND device_id != 'ioc_test_device' ORDER BY received_at DESC LIMIT 1;"
    device_id = run_psql(query)
    if not device_id:
        print("No real device found.")
    else:
        print(f"Likely real device: {device_id}")

    print("\n--- 2. Sampling behavior_events ---")
    counts = []
    live_ingestion = False
    if device_id:
        for i in range(4):
            c = run_psql(f"SELECT COUNT(*) FROM behavior_events WHERE device_id = '{device_id}';")
            counts.append(int(c) if c.isdigit() else 0)
            if i < 3: time.sleep(6)
        print(f"Samples: {counts}")
        if len(counts) > 1 and counts[-1] > counts[0]:
            live_ingestion = True
    
    # Corrected Ports based on docker ps
    EDGE_URL = "http://localhost:8000"
    DASH_URL = "http://localhost:5001"

    print("\n--- 3. Device Stats ---")
    edge_api = False
    if device_id:
        stats = get_json(f"{EDGE_URL}/api/stats/{device_id}")
        if isinstance(stats, dict):
            edge_api = True
            print(f"Stats: baselineSamples={stats.get('baselineSamples')}, distanceMean={stats.get('distanceMean')}, distanceStd={stats.get('distanceStd')}, isActive={stats.get('isActive')}, lastSeen={stats.get('lastSeen')}")
        else:
            print(f"Stats failed: {stats}")

    print("\n--- 4. Device Alerts ---")
    if device_id:
        alerts = get_json(f"{EDGE_URL}/api/alerts/{device_id}?limit=5")
        if isinstance(alerts, list):
            print(f"Alert count: {len(alerts)}")
        else:
            print(f"Alerts failed: {alerts}")

    print("\n--- 5. Dashboard APIs ---")
    sum_data = get_json(f"{DASH_URL}/api/dashboard/summary")
    evt_data = get_json(f"{DASH_URL}/api/dashboard/events")
    alr_data = get_json(f"{DASH_URL}/api/dashboard/alerts")
    dashboard_api = isinstance(sum_data, dict) and isinstance(evt_data, list) and isinstance(alr_data, list)
    print(f"Dashboard summary items: {len(sum_data) if dashboard_api else 'Error'}")

    print("\n--- 6. ADB Bridge API ---")
    adb_status = get_json(f"{DASH_URL}/api/adb/status")
    adb_logs = get_json(f"{DASH_URL}/api/adb/logs?limit=20")
    adb_bridge = isinstance(adb_status, dict) and isinstance(adb_logs, list)
    print(f"ADB State: {adb_status.get('state') if isinstance(adb_status, dict) else 'Error'}")

    print("\n--- 7. Native ADB ---")
    try:
        adb_out = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True).stdout
        print(adb_out.strip())
    except Exception as e:
        print(f"ADB command failed: {e}")

    print("\n--- RESULTS ---")
    print(f"live_ingestion: {'PASS' if live_ingestion else 'FAIL'}")
    print(f"edge_api: {'PASS' if edge_api else 'FAIL'}")
    print(f"dashboard_api: {'PASS' if dashboard_api else 'FAIL'}")
    print(f"adb_bridge: {'PASS' if adb_bridge else 'FAIL'}")

if __name__ == '__main__':
    main()
