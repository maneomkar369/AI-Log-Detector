import asyncio
import websockets
import json
import time

async def trigger_events():
    uri = "ws://localhost:8000/ws"
    device_id = "test_simulator_123"
    
    async with websockets.connect(f"{uri}/{device_id}") as websocket:
        print("Connected to Edge Server via WS!")
        
        # 1. Simulate Phishing Domain Event
        phishing_payload = [
            {
                "type": "WEB_DOMAIN",
                "packageName": "com.android.chrome",
                "timestamp": int(time.time() * 1000),
                "data": json.dumps({
                    "domain": "paypal-secure-login.tk",
                    "url": "https://paypal-secure-login.tk/auth",
                    "source": "accessibility"
                })
            }
        ]
        
        print(f"Sending phishing event: {phishing_payload}")
        await websocket.send(json.dumps(phishing_payload))
        await asyncio.sleep(2)  # Wait for processing
        
        # 2. Simulate Sideloaded App Permission Event
        permission_payload = [
            {
                "type": "PERMISSION_ACCESS",
                "packageName": "com.evil.spyware",
                "timestamp": int(time.time() * 1000),
                "data": json.dumps({
                    "permission": "CAMERA",
                    "packageName": "com.evil.spyware",
                    "isSideLoaded": True,
                    "installerPackage": "com.android.chrome",
                    "uid": 10245
                })
            }
        ]
        
        print(f"Sending permission event: {permission_payload}")
        await websocket.send(json.dumps(permission_payload))
        await asyncio.sleep(2)
        
        # 3. Simulate Canary File Access Event
        canary_payload = [
            {
                "type": "CANARY_FILE_ACCESS",
                "packageName": "com.evil.ransomware",
                "timestamp": int(time.time() * 1000),
                "data": json.dumps({
                    "fileName": "passwords_backup.txt",
                    "action": "MODIFY",
                    "urgency": "CRITICAL"
                })
            }
        ]
        
        print(f"Sending canary access event: {canary_payload}")
        await websocket.send(json.dumps(canary_payload))
        await asyncio.sleep(2)
        
        print("Events sent. Check dashboard for alerts.")

if __name__ == "__main__":
    asyncio.run(trigger_events())
