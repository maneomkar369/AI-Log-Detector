import json
import subprocess
import time
import urllib.request
import urllib.error

EDGE = 'http://localhost:8000'
DASH = 'http://localhost:5001'
PHONE_DEVICE = 'f9ed08dc27055482'
SYN_DEVICE = 'smoke_action_e2e'

results = {}

def get_json(url, timeout=15):
    req = urllib.request.Request(url, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.getcode(), json.loads(r.read().decode())

def post_json(url, payload, timeout=20):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method='POST', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.getcode(), json.loads(r.read().decode())

def alert_id(alert):
    return alert.get('anomalyId') or alert.get('anomaly_id') or alert.get('id')

# 1) Health
try:
    c1, h = get_json(f'{EDGE}/api/health')
    c2, s = get_json(f'{DASH}/api/dashboard/summary')
    ok = c1 == 200 and c2 == 200 and h.get('status') == 'ok'
    results['health_endpoints'] = {'pass': ok, 'detail': f'edge={c1}, dash={c2}'}
except Exception as e:
    results['health_endpoints'] = {'pass': False, 'detail': str(e)}

# 2) Phone alerts + XAI
phone_alerts = []
try:
    c, phone_alerts = get_json(f'{EDGE}/api/alerts/{PHONE_DEVICE}?limit=20')
    has_alerts = isinstance(phone_alerts, list) and len(phone_alerts) > 0
    has_xai = False
    if has_alerts:
        for a in phone_alerts:
            x = a.get('xaiExplanation') or a.get('xai_explanation') or {}
            if isinstance(x, dict) and str(x.get('summary','')).strip():
                has_xai = True
                break
    results['phone_alerts_xai'] = {'pass': has_alerts and has_xai, 'detail': f'alerts={len(phone_alerts) if isinstance(phone_alerts,list) else 0}, xai={has_xai}'}
except Exception as e:
    results['phone_alerts_xai'] = {'pass': False, 'detail': str(e)}

# 3) Deny workflow on phone pending alert
phone_denied_id = None
try:
    pending = None
    for a in phone_alerts if isinstance(phone_alerts, list) else []:
        if str(a.get('status','')).lower() == 'pending' and alert_id(a):
            pending = a
            break
    if pending is None:
        results['phone_deny_workflow'] = {'pass': False, 'detail': 'no pending phone alert available'}
    else:
        aid = alert_id(pending)
        c, resp = post_json(f'{EDGE}/api/alerts/{aid}/deny', {})
        c2, after = get_json(f'{EDGE}/api/alerts/{PHONE_DEVICE}?limit=20')
        status = None
        for a in after:
            if alert_id(a) == aid:
                status = str(a.get('status','')).lower()
                break
        ok = c == 200 and status == 'denied'
        phone_denied_id = aid
        results['phone_deny_workflow'] = {'pass': ok, 'detail': f'alert={aid}, status_after={status}'}
except Exception as e:
    results['phone_deny_workflow'] = {'pass': False, 'detail': str(e)}

# 4) Synthetic approve workflow
approved_syn_id = None
try:
    py = (
        "import asyncio,json,time,websockets\n"
        "async def main():\n"
        f"  uri='ws://127.0.0.1:8000/ws/{SYN_DEVICE}'\n"
        "  async with websockets.connect(uri) as ws:\n"
        "    now=int(time.time()*1000)\n"
        "    b1=[{'type':'SECURITY_PACKAGE_EVENT','packageName':'com.example.risky','timestamp':now+i*20,'data':json.dumps({'action':'android.intent.action.PACKAGE_ADDED'})} for i in range(50)]\n"
        "    await ws.send(json.dumps(b1))\n"
        "    await asyncio.sleep(0.7)\n"
        "    now2=int(time.time()*1000)\n"
        "    b2=[{'type':'SECURITY_PACKAGE_EVENT','packageName':'com.example.risky','timestamp':now2+i*20,'data':json.dumps({'action':'android.intent.action.PACKAGE_REPLACED'})} for i in range(50)]\n"
        "    await ws.send(json.dumps(b2))\n"
        "    await asyncio.sleep(1.0)\n"
        "asyncio.run(main())\n"
    )
    subprocess.check_call(['docker','compose','exec','-T','edge_server','python','-c',py])
    time.sleep(1)
    c, syn_alerts = get_json(f'{EDGE}/api/alerts/{SYN_DEVICE}?limit=10')
    sid = None
    for a in syn_alerts:
        if alert_id(a):
            sid = alert_id(a)
            break
    if not sid:
        results['synthetic_approve_workflow'] = {'pass': False, 'detail': 'no synthetic alert generated'}
    else:
        c2, resp = post_json(f'{EDGE}/api/alerts/{sid}/approve', {})
        actions = resp.get('actionsExecuted') if isinstance(resp, dict) else None
        ok = c2 == 200 and resp.get('status') == 'approved' and isinstance(actions, list)
        approved_syn_id = sid
        results['synthetic_approve_workflow'] = {'pass': ok, 'detail': f'alert={sid}, actions={len(actions) if isinstance(actions,list) else -1}'}
except Exception as e:
    results['synthetic_approve_workflow'] = {'pass': False, 'detail': str(e)}

# 5) Dashboard propagation
try:
    c, d_alerts = get_json(f'{DASH}/api/dashboard/alerts')
    target_ids = {x for x in [phone_denied_id, approved_syn_id] if x}
    found = False
    found_detail = 'none'
    if isinstance(d_alerts, list) and target_ids:
        for a in d_alerts:
            aid = alert_id(a)
            if aid in target_ids:
                found = True
                found_detail = f'{aid}:{a.get("status")}'
                break
    results['dashboard_status_propagation'] = {'pass': found, 'detail': found_detail}
except Exception as e:
    results['dashboard_status_propagation'] = {'pass': False, 'detail': str(e)}

# 6) ADB bridge
try:
    c1, st = get_json(f'{DASH}/api/adb/status')
    c2, logs = get_json(f'{DASH}/api/adb/logs?limit=20')
    ok = c1 == 200 and c2 == 200 and bool(st.get('connected')) and isinstance(logs, list)
    results['adb_bridge'] = {'pass': ok, 'detail': f'connected={st.get("connected")}, logs={len(logs) if isinstance(logs,list) else -1}'}
except Exception as e:
    results['adb_bridge'] = {'pass': False, 'detail': str(e)}

# 7) FL flow
try:
    c1, r1 = post_json(f'{EDGE}/api/fl/register', {'device_id':'fl_phone_test_1'})
    c2, r2 = post_json(f'{EDGE}/api/fl/register', {'device_id':'fl_phone_test_2'})
    cid1 = r1.get('client_id')
    cid2 = r2.get('client_id')
    c3, u1 = post_json(f'{EDGE}/api/fl/update', {'client_id':cid1,'round_id':1,'base_model_version':1,'num_samples':10,'weights_delta':[0.1,0.2,0.3]})
    c4, u2 = post_json(f'{EDGE}/api/fl/update', {'client_id':cid2,'round_id':1,'base_model_version':1,'num_samples':20,'weights_delta':[0.0,0.1,0.2]})
    c5, ag = post_json(f'{EDGE}/api/fl/aggregate', {'round_id':1,'force':False})
    c6, model = get_json(f'{EDGE}/api/fl/model')
    gmv = int(model.get('global_model_version',0))
    ok = (c1==200 and c2==200 and c3==200 and c4==200 and c5==200 and c6==200 and gmv >= 2)
    results['federated_scaffold'] = {'pass': ok, 'detail': f'global_model_version={gmv}, aggregate_status={ag.get("status")}' }
except Exception as e:
    results['federated_scaffold'] = {'pass': False, 'detail': str(e)}

print(json.dumps(results, indent=2, sort_keys=True))
