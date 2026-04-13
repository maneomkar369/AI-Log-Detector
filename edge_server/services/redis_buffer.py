"""
Redis Buffer — Event Buffering & Pub/Sub
==========================================
Buffers incoming behavioral events in Redis before batch database insert.
Provides pub/sub for real-time dashboard streaming.
"""

import json
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class RedisBuffer:
    """
    Redis-backed event buffer and pub/sub manager.

    Buffers events in Redis lists and publishes to channels
    for real-time dashboard consumption.
    """

    BUFFER_KEY_PREFIX = "events:"
    ALERTS_CHANNEL = "alerts"
    EVENTS_CHANNEL = "events"
    BATCH_SIZE = 50

    def __init__(self, redis_client=None):
        self.redis = redis_client

    async def connect(self, redis_url: str) -> None:
        """Initialize async Redis connection."""
        import redis.asyncio as aioredis
        self.redis = aioredis.from_url(redis_url, decode_responses=True)
        logger.info("Redis connected: %s", redis_url)

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()

    async def buffer_event(self, device_id: str, event: dict) -> int:
        """
        Push an event to the device's Redis buffer list.

        Returns the current buffer length.
        """
        key = f"{self.BUFFER_KEY_PREFIX}{device_id}"
        length = await self.redis.rpush(key, json.dumps(event))
        # Set TTL to 1 hour (safety net)
        await self.redis.expire(key, 3600)
        return length

    async def flush_buffer(self, device_id: str) -> List[dict]:
        """
        Pop all buffered events for a device (atomic).

        Returns
        -------
        list[dict] — events ready for batch DB insert
        """
        key = f"{self.BUFFER_KEY_PREFIX}{device_id}"

        # Atomic pop of up to BATCH_SIZE items
        pipe = self.redis.pipeline()
        pipe.lrange(key, 0, self.BATCH_SIZE - 1)
        pipe.ltrim(key, self.BATCH_SIZE, -1)
        results = await pipe.execute()

        events = []
        for raw in results[0]:
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed event: %s", raw[:100])
        return events

    async def get_buffer_size(self, device_id: str) -> int:
        """Return current buffer length for a device."""
        key = f"{self.BUFFER_KEY_PREFIX}{device_id}"
        return await self.redis.llen(key)

    # ────────────────── Pub/Sub ──────────────────

    async def publish_alert(self, alert_data: dict) -> None:
        """Publish an alert to the alerts channel (for dashboard)."""
        await self.redis.publish(
            self.ALERTS_CHANNEL, json.dumps(alert_data)
        )

    async def publish_event(self, event_data: dict) -> None:
        """Publish a raw event to the events channel (for dashboard log viewer)."""
        await self.redis.publish(
            self.EVENTS_CHANNEL, json.dumps(event_data)
        )

    async def subscribe_alerts(self):
        """Return an async pub/sub subscriber for alerts."""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.ALERTS_CHANNEL)
        return pubsub

    async def subscribe_events(self):
        """Return an async pub/sub subscriber for events."""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.EVENTS_CHANNEL)
        return pubsub
