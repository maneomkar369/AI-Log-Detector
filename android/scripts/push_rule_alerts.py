import asyncio
import json
import random
import sys
import time

import websockets


async def push_windows(server_url: str, device_id: str, windows: int = 6, batch_size: int = 50) -> None:
    uri = f"{server_url.rstrip('/')}/{device_id}"
    print(f"Connecting to {uri}")

    async with websockets.connect(uri) as ws:
        print("Connected. Sending anomaly windows...")
        received_alerts = 0

        for window in range(1, windows + 1):
            now = int(time.time() * 1000)
            events = []
            for idx in range(batch_size):
                events.append(
                    {
                        "type": "SECURITY_PACKAGE_EVENT",
                        "packageName": random.choice(
                            [
                                "com.android.settings",
                                "com.whatsapp",
                                "com.instagram.android",
                                "com.google.android.gms",
                            ]
                        ),
                        "timestamp": now + idx,
                        "data": {
                            "action": random.choice(
                                [
                                    "PACKAGE_ADDED",
                                    "PACKAGE_REMOVED",
                                    "PACKAGE_REPLACED",
                                ]
                            )
                        },
                    }
                )

            await ws.send(json.dumps(events))
            print(f"Window {window}/{windows}: sent {len(events)} events")

            # Pull any alert responses emitted for this device.
            deadline = time.time() + 1.2
            while time.time() < deadline:
                timeout = max(0.05, deadline - time.time())
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    break

                try:
                    payload = json.loads(response)
                except json.JSONDecodeError:
                    continue

                if isinstance(payload, dict) and payload.get("type") == "alert":
                    received_alerts += 1
                    print(
                        f"  Alert {received_alerts}: severity={payload.get('severity')} type={payload.get('threatType')}"
                    )

            await asyncio.sleep(0.35)

        print(f"Completed. Received {received_alerts} alert messages in this session.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python push_rule_alerts.py <device_id> [server_url]")
        sys.exit(1)

    device = sys.argv[1]
    server = sys.argv[2] if len(sys.argv) > 2 else "wss://grid-scuff-diploma.ngrok-free.dev/ws"
    asyncio.run(push_windows(server, device))
