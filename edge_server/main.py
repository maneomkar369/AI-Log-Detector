"""
Edge Server — Main Application
================================
FastAPI application with WebSocket ingestion, REST API,
and lifecycle management for database and Redis.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from models.database import init_db
from services.redis_buffer import RedisBuffer
from api.websocket_handler import ConnectionManager
from api.rest_routes import router as api_router
import hmac
import hashlib

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("edge_server")

# ── Shared State ──
redis_buffer = RedisBuffer()
connection_manager: ConnectionManager = None  # Initialized in lifespan


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    global connection_manager

    logger.info("Starting edge server...")

    # Initialize database tables
    await init_db()
    logger.info("Database initialized")

    # Connect to Redis
    try:
        await redis_buffer.connect(settings.redis_url)
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis not available (%s) — running without buffer", e)

    # Initialize connection manager
    connection_manager = ConnectionManager(redis_buffer)
    app.state.connection_manager = connection_manager

    # Start ADB connection monitor
    try:
        from services.action_executor import ActionExecutor
        from services.adb_monitor import AdbConnectionMonitor
        action_executor = ActionExecutor()
        adb_monitor = AdbConnectionMonitor(action_executor)
        # Run monitor in background
        import asyncio
        asyncio.create_task(adb_monitor.start_monitoring())
    except Exception as e:
        logger.warning("Failed to start ADB connection monitor: %s", e)

    # Start database cleanup scheduler
    try:
        from services.db_cleanup import db_cleanup_service
        await db_cleanup_service.start_cleanup_scheduler()
    except Exception as e:
        logger.warning("Failed to start database cleanup scheduler: %s", e)

    logger.info(
        "Edge server ready on %s:%d",
        settings.edge_server_host, settings.edge_server_port,
    )
    yield

    # Shutdown
    await redis_buffer.close()
    logger.info("Edge server shut down")


# ── FastAPI App ──
app = FastAPI(
    title="Behavioral Log Anomaly Detector",
    description="Edge server for real-time Android behavioral anomaly detection",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS (allow dashboard and Android app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST routes
app.include_router(api_router)


# ── WebSocket Endpoint ──

@app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str, token: str = ""):
    """
    WebSocket endpoint for Android device communication.

    Devices connect and stream behavioral events as JSON arrays.
    The server responds with alerts when anomalies are detected.
    """
    # Flaw #16: HMAC Authentication
    expected_token = hmac.new(
        settings.device_shared_secret.encode("utf-8"),
        device_id.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected_token, token):
        logger.warning("Unauthorized WebSocket connection attempt for device %s", device_id)
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await connection_manager.connect(device_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            logger.info("Received WebSocket data from %s (length: %d)", device_id, len(data))
            await connection_manager.handle_message(device_id, data)
    except WebSocketDisconnect:
        connection_manager.disconnect(device_id, websocket)
    except Exception as e:
        logger.exception("WebSocket error for %s: %s", device_id, e)
        connection_manager.disconnect(device_id, websocket)


# ── Root ──

@app.get("/")
async def root():
    return {
        "service": "Behavioral Log Anomaly Detector",
        "version": "1.0.0",
        "docs": "/docs",
        "websocket": "/ws/{device_id}",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.edge_server_host,
        port=settings.edge_server_port,
        reload=True,
    )
