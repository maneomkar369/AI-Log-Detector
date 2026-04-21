import json
import subprocess
import time

# Based on docker logs and docker ps:
# dashboard-1 on 5001 (internal 5000)
# edge_server-1 on 8000
DASHBOARD_URL = "http://localhost:5001"
EDGE_URL = "http://localhost:8000"

def run_command(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return "", str(e), 1

def check_endpoint(url, path):
    stdout, stderr, code = run_command(f"curl -s -o /dev/null -w '%{{http_code}}' {url}{path}")
    return stdout.strip() == "200", stdout.strip()

def get_json(url, path):
    stdout, stderr, code = run_command(f"curl -s {url}{path}")
    try:
        return json.loads(stdout)
    except:
        return None

def post_json(url, path, data=None):
    if data:
        stdout, stderr, code = run_command(f"curl -s -X POST -H 'Content-Type: application/json' -d '{json.dumps(data)}' {url}{path}")
    else:
        stdout, stderr, code = run_command(f"curl -s -X POST {url}{path}")
    try:
        return json.loads(stdout)
    except:
        return None

results = {}

# 1) Edge health and dashboard summary
edge_health_ok, edge_health_code = check_endpoint(EDGE_URL, "/api/health")
dash_summary_ok, dash_summary_code = check_endpoint(DASHBOARD_URL, "/api/dashboard/summary")
results["1_health_summary"] = {"pass": bool(edge_health_ok and dash_summary_ok), "detail": f"Edge: {edge_health_code}, Dash: {dash_summary_code}"}

# 2) Phone alerts for f9ed08dc27055482
# In edge_server logs, /api/alerts/f9ed08dc27055482?limit=5 was called. Let's try that.
alerts = get_json(EDGE_URL, "/api/alerts/f9ed08dc27055482?limit=50")
phone_alerts_exist = isinstance(alerts, list) and len(alerts) > 0
has_xai = any(a.get("xaiExplanation", {}).get("summary") for a in alerts) if phone_alerts_exist else False
results["2_phone_alerts"] = {"pass": bool(phone_alerts_exist and has_xai), "detail": f"Alerts: {len(alerts) if alerts else 0}, Has XAI: {has_xai}"}

# 3) Deny workflow
# Try to find a pending alert
pending_deny = next((a for a in alerts if a.get("status") == "pending"), None) if phone_alerts_exist else None
if not pending_deny and phone_alerts_exist:
    # If no pending, we'll try to use the last one anyway just to see if the endpoint works or exists
    pending_deny = alerts[0]

if pending_deny:
    deny_res = post_json(EDGE_URL, f"/api/alerts/{pending_deny['id']}/deny")
    updated_alert = get_json(EDGE_URL, f"/api/alerts/f9ed08dc27055482")
    # Finding the updated one in the list
    upd = next((a for a in updated_alert if a["id"] == pending_deny["id"]), None) if isinstance(updated_alert, list) else None
    deny_ok = upd and upd.get("status") == "denied"
    results["3_deny_workflow"] = {"pass": bool(deny_ok), "detail": f"ID {pending_deny['id']} status: {upd.get('status') if upd else 'N/A'}"}
else:
    results["3_deny_workflow"] = {"pass": False, "detail": "No alert found for f9ed08dc27055482"}

# 4) Safe approve workflow
print("Injecting events for smoke_action_e2e...")
# Edge server usually listens on 5051 for internal log event distribution.
# Let's use the container internal port.
inject_cmd = "docker exec ai-log-detector-edge_server-1 python3 -c \"import socket, json, time; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.connect(('127.0.0.1', 5051)); [s.sendall(json.dumps({'device_id': 'smoke_action_e2e', 'type': 'SECURITY_PACKAGE_EVENT', 'events': [{'id': str(i), 'timestamp': time.time()} for i in range(50)]}).encode() + b'\\n') for _ in range(2)]; s.close()\""
run_command(inject_cmd)
time.sleep(3)

synth_alerts = get_json(EDGE_URL, "/api/alerts/smoke_action_e2e")
latest_id = None
if synth_alerts and len(synth_alerts) > 0:
    latest_id = synth_alerts[0]["id"]
    approve_res = post_json(DASHBOARD_URL, f"/api/alerts/{latest_id}/approve")
    # Some apps use EDGE_URL for POST, others use DASHBOARD_URL. Let's try EDGE_URL if DASH fails.
    if not approve_res or "status" not in approve_res:
        approve_res = post_json(EDGE_URL, f"/api/alerts/{latest_id}/approve")
    
    approve_ok = approve_res and approve_res.get("status") == "approved" and "actionsExecuted" in approve_res
    results["4_approve_workflow"] = {"pass": bool(approve_ok), "detail": f"ID {latest_id} status: {approve_res.get('status') if approve_res else 'fail'}"}
else:
    results["4_approve_workflow"] = {"pass": False, "detail": "No alerts created for smoke_action_e2e"}

# 5) Dashboard propagation
dash_alerts = get_json(DASHBOARD_URL, "/api/dashboard/alerts")
id_to_check = None
if results["3_deny_workflow"]["pass"]: id_to_check = pending_deny["id"]
elif results["4_approve_workflow"]["pass"]: id_to_check = latest_id

dash_ok = any(str(a["id"]) == str(id_to_check) for a in dash_alerts) if dash_alerts and id_to_check else False
if not dash_ok and id_to_check:
    # Try a simple check if the ID exists in the full list
    dash_ok = id_to_check in str(dash_alerts)

results["5_dashboard_propagation"] = {"pass": bool(dash_ok), "detail": f"Found ID {id_to_check} in dashboard: {dash_ok}"}

# 6) ADB bridge
adb_status = get_json(DASHBOARD_URL, "/api/adb/status")
adb_logs = get_json(DASHBOARD_URL, "/api/adb/logs?limit=20")
adb_ok = adb_status and adb_status.get("connected") is True and isinstance(adb_logs, list)
results["6_adb_bridge"] = {"pass": bool(adb_ok), "detail": f"Connected: {adb_status.get('connected') if adb_status else 'N/A'}, Logs count: {len(adb_logs) if adb_logs else 0}"}

# 7) Federated scaffold flow
# Using EDGE_URL for FL based on previous experience with this project.
fl_base = EDGE_URL
post_json(fl_base, "/api/fl/register", {"client_id": "c1"})
post_json(fl_base, "/api/fl/register", {"client_id": "c2"})
post_json(fl_base, "/api/fl/update", {"client_id": "c1", "round": 1, "model_version": 1, "weights": [0.1, 0.2]})
post_json(fl_base, "/api/fl/update", {"client_id": "c2", "round": 1, "model_version": 1, "weights": [0.2, 0.3]})
post_json(fl_base, "/api/fl/aggregate", {"round": 1})
fl_model = get_json(fl_base, "/api/fl/model")
fl_ok = fl_model and fl_model.get("global_model_version", 0) >= 2
results["7_federated_flow"] = {"pass": bool(fl_ok), "detail": f"Global model version: {fl_model.get('global_model_version') if fl_model else 'N/A'}"}

print(json.dumps(results, indent=2))
