"""
Dashboard — Flask + Socket.IO
===============================
Real-time web dashboard for monitoring Android device behavior,
viewing alerts, and controlling threat responses.
"""

import os
import json
import threading
from datetime import datetime

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("DASHBOARD_SECRET_KEY", "dev-secret")

    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

    # ── In-memory state (bridged from edge server via Redis) ──
    recent_events = []
    recent_alerts = []
    MAX_EVENTS = 500
    MAX_ALERTS = 100

    # ── Routes ──

    @app.route("/")
    def index():
        """Real-time log viewer."""
        return render_template("index.html")

    @app.route("/alerts")
    def alerts_page():
        """Alert history and action controls."""
        return render_template("alerts.html")

    @app.route("/api/dashboard/events")
    def api_events():
        """Return recent events (for initial load)."""
        return jsonify(recent_events[-100:])

    @app.route("/api/dashboard/alerts")
    def api_alerts():
        """Return recent alerts (for initial load)."""
        return jsonify(recent_alerts[-50:])

    # ── Socket.IO Events ──

    @socketio.on("connect")
    def handle_connect():
        """Client connected to dashboard."""
        print(f"[Dashboard] Client connected: {request.sid}")

    @socketio.on("disconnect")
    def handle_disconnect():
        """Client disconnected."""
        print(f"[Dashboard] Client disconnected: {request.sid}")

    # ── Redis Subscriber (Background Thread) ──

    def redis_listener():
        """Subscribe to Redis channels and forward to Socket.IO clients."""
        try:
            import redis as redis_lib
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            r = redis_lib.from_url(redis_url)
            pubsub = r.pubsub()
            pubsub.subscribe("events", "alerts")
            print("[Dashboard] Redis subscriber started")

            for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()
                data = json.loads(message["data"])

                if channel == "events":
                    data["_received"] = datetime.utcnow().isoformat()
                    recent_events.append(data)
                    if len(recent_events) > MAX_EVENTS:
                        recent_events.pop(0)
                    socketio.emit("new_event", data)

                elif channel == "alerts":
                    data["_received"] = datetime.utcnow().isoformat()
                    recent_alerts.append(data)
                    if len(recent_alerts) > MAX_ALERTS:
                        recent_alerts.pop(0)
                    socketio.emit("new_alert", data)

        except Exception as e:
            print(f"[Dashboard] Redis subscriber error: {e}")
            print("[Dashboard] Running without live Redis updates")

    # Start Redis listener in background
    listener_thread = threading.Thread(target=redis_listener, daemon=True)
    listener_thread.start()

    return app, socketio


if __name__ == "__main__":
    app, socketio = create_app()
    port = int(os.getenv("DASHBOARD_PORT", 5000))
    print(f"\n{'='*50}")
    print(f"  📊 ANOMALY DETECTOR DASHBOARD")
    print(f"  http://localhost:{port}")
    print(f"{'='*50}\n")
    socketio.run(app, host="0.0.0.0", port=port, debug=True)
