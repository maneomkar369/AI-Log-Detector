"""
Soak Test (Load Testing) for AI Log Detector
=============================================
Simulates highly concurrent event ingestion over WebSockets to validate
the performance of the Mahalanobis anomaly detection, Fast-path routing,
and Redis event buffering locally.
"""

import asyncio
import json
import logging
import random
import time
import websockets
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

WS_URL = "ws://localhost:8000/ws/"
CONCURRENT_DEVICES = 50
EVENTS_PER_DEVICE = 1000
BATCH_SIZE = 50      # Events per WS message
DELAY_BETWEEN_BATCHES = 0.5  # Seconds

@dataclass
class TestMetrics:
    total_events_sent: int = 0
    successful_batches: int = 0
    failed_batches: int = 0
    start_time: float = 0
    end_time: float = 0

    @property
    def events_per_second(self) -> float:
        duration = self.end_time - self.start_time
        if duration <= 0: return 0.0
        return self.total_events_sent / duration

metrics = TestMetrics()

def generate_random_event(device_id: str):
    """Generates a pseudo-random behavioral event."""
    event_types = ["KEYSTROKE_DYNAMICS", "TOUCH_DYNAMICS", "WEB_DOMAIN", "APP_TRANSITION", "PERMISSION_ACCESS"]
    ev_type = random.choices(event_types, weights=[40, 40, 10, 8, 2], k=1)[0]
    
    timestamp = int(time.time() * 1000)
    
    if ev_type == "KEYSTROKE_DYNAMICS":
        return {
            "type": ev_type,
            "packageName": "com.example.app",
            "timestamp": timestamp,
            "data": {
                "flightTime": random.uniform(50, 150),
                "dwellTime": random.uniform(30, 80),
                "errorRate": random.uniform(0, 0.1)
            }
        }
    elif ev_type == "WEB_DOMAIN":
        domain = random.choice(["google.com", "paypal-secure-login.tk", "facebook.com", "amazon.com"])
        return {
            "type": ev_type,
            "packageName": "com.android.chrome",
            "timestamp": timestamp,
            "data": {
                "domain": domain,
                "tfliteScore": random.uniform(0.0, 0.9) if "tk" in domain else random.uniform(0.0, 0.2)
            }
        }
    elif ev_type == "PERMISSION_ACCESS":
        return {
            "type": ev_type,
            "packageName": "com.sideloaded.malware",
            "timestamp": timestamp,
            "data": {
                "permission": "CAMERA",
                "isSideLoaded": True
            }
        }
    else:
        return {
            "type": ev_type,
            "packageName": "com.example.app",
            "timestamp": timestamp,
            "data": {"value": random.random()}
        }

async def simulate_device(device_id: str):
    """Simulates a single Android device sending batches of events."""
    uri = f"{WS_URL}{device_id}"
    
    try:
        async with websockets.connect(uri) as websocket:
            logger.info(f"Device {device_id} connected.")
            events_sent = 0
            
            while events_sent < EVENTS_PER_DEVICE:
                batch = [generate_random_event(device_id) for _ in range(BATCH_SIZE)]
                
                try:
                    await websocket.send(json.dumps(batch))
                    metrics.successful_batches += 1
                    metrics.total_events_sent += len(batch)
                    events_sent += len(batch)
                except Exception as e:
                    metrics.failed_batches += 1
                    logger.error(f"Device {device_id} failed to send batch: {e}")
                    break
                
                await asyncio.sleep(DELAY_BETWEEN_BATCHES)
                
            logger.info(f"Device {device_id} finished. Sent {events_sent} events.")
    except Exception as e:
        logger.error(f"Device {device_id} connection failed: {e}")

async def run_soak_test():
    metrics.start_time = time.time()
    logger.info(f"Starting Soak Test: {CONCURRENT_DEVICES} devices, {EVENTS_PER_DEVICE} events each.")
    
    tasks = []
    for i in range(CONCURRENT_DEVICES):
        device_id = f"test_device_{i:03d}"
        tasks.append(simulate_device(device_id))
        
    await asyncio.gather(*tasks)
    
    metrics.end_time = time.time()
    
    logger.info("====================================")
    logger.info("         SOAK TEST RESULTS")
    logger.info("====================================")
    logger.info(f"Duration:             {metrics.end_time - metrics.start_time:.2f} seconds")
    logger.info(f"Total Events Sent:    {metrics.total_events_sent}")
    logger.info(f"Successful Batches:   {metrics.successful_batches}")
    logger.info(f"Failed Batches:     {metrics.failed_batches}")
    logger.info(f"Throughput:           {metrics.events_per_second:.2f} events/sec")
    logger.info("====================================")

if __name__ == "__main__":
    asyncio.run(run_soak_test())
