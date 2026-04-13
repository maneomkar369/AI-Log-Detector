"""
Load Test — Simulate N Concurrent WebSocket Devices
=====================================================
Simulates multiple Android devices connecting to the edge server
and streaming behavioral events for load testing.

Usage:
    python simulate_devices.py --devices 50 --duration 300
"""

import asyncio
import json
import random
import time
import argparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("load_test")


async def simulate_device(device_id: str, server_url: str, duration: int):
    """Simulate a single Android device."""
    import websockets

    apps = [
        "com.whatsapp", "com.instagram", "com.chrome",
        "com.spotify", "com.gmail", "com.slack",
        "com.tiktok", "com.twitter", "com.youtube",
    ]

    try:
        async with websockets.connect(f"{server_url}/{device_id}") as ws:
            logger.info("Device %s connected", device_id)
            start = time.time()

            while time.time() - start < duration:
                # Generate a batch of events
                events = []
                batch_size = random.randint(5, 20)

                for _ in range(batch_size):
                    event_type = random.choice(["APP_USAGE", "KEYSTROKE", "TOUCH", "SWIPE"])
                    events.append({
                        "type": event_type,
                        "packageName": random.choice(apps),
                        "timestamp": int(time.time() * 1000),
                        "data": json.dumps({"value": random.random()}),
                    })

                await ws.send(json.dumps(events))

                # Read any responses (alerts)
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    data = json.loads(response)
                    if data.get("type") == "alert":
                        logger.warning(
                            "🚨 Device %s got alert: severity=%s",
                            device_id, data.get("severity"),
                        )
                except asyncio.TimeoutError:
                    pass

                # Wait between batches
                await asyncio.sleep(random.uniform(5, 15))

            logger.info("Device %s completed (%ds)", device_id, duration)

    except Exception as e:
        logger.error("Device %s error: %s", device_id, e)


async def main(num_devices: int, duration: int, server_url: str):
    logger.info(
        "Starting load test: %d devices, %ds duration, server=%s",
        num_devices, duration, server_url,
    )

    tasks = [
        simulate_device(f"test_device_{i:04d}", server_url, duration)
        for i in range(num_devices)
    ]

    # Stagger connections (100ms apart)
    staggered = []
    for i, task in enumerate(tasks):
        staggered.append(asyncio.create_task(task))
        if i < len(tasks) - 1:
            await asyncio.sleep(0.1)

    await asyncio.gather(*staggered)
    logger.info("Load test complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load test simulator")
    parser.add_argument("--devices", type=int, default=10, help="Number of simulated devices")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--server", default="ws://localhost:8000/ws",
                        help="WebSocket server URL")
    args = parser.parse_args()

    asyncio.run(main(args.devices, args.duration, args.server))
