"""
Tests for REST API
===================
"""

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from test_server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_root_endpoint(client):
    """Root should return service info."""
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "service" in data


def test_health_endpoint(client):
    """Health check should return ok."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_get_alerts_empty(client):
    """Alerts for unknown device should return empty list."""
    resp = client.get("/api/alerts/unknown_device")
    assert resp.status_code == 200
    assert resp.json() == []


def test_approve_nonexistent_alert(client):
    """Approving a nonexistent alert should return error."""
    resp = client.post("/api/alerts/fake_alert/approve")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data or "status" in data
