"""
Unit and Integration Tests for Remote Google Sheets Kill-Switch & License System
================================================================================
"""

import pytest
from fastapi.testclient import TestClient
from main import app
from database import get_setting, set_setting
import license_manager

client = TestClient(app)

def setup_function():
    # Reset license status to ACTIVE before each test
    set_setting("license_status", "ACTIVE")
    set_setting("license_block_message", "Software License Suspended. Please contact developer for renewal.")
    set_setting("license_dev_contact", "0316-6868169")

def teardown_function():
    # Ensure system is left in ACTIVE state
    set_setting("license_status", "ACTIVE")

def test_license_status_endpoint_active():
    """Verify that by default system is ACTIVE and unblocked."""
    set_setting("license_status", "ACTIVE")
    res = client.get("/api/license/status")
    assert res.status_code == 200
    data = res.json()
    assert data["blocked"] is False
    assert data["status"] == "ACTIVE"

def test_offline_resilience_fail_open():
    """Verify that when offline or invalid URL, check_remote_sheet fails safely without blocking."""
    set_setting("license_status", "ACTIVE")
    set_setting("google_sheet_csv_url", "http://192.0.2.1/invalid_non_existent.csv") # Unreachable IP

    # Should not raise exception and should not block the system
    result = license_manager.check_remote_sheet(timeout=1)
    assert result["success"] is False
    
    # Crucial: local status MUST remain ACTIVE (fail-open)
    state = license_manager.get_license_state()
    assert state["blocked"] is False
    assert state["status"] == "ACTIVE"

def test_system_block_enforcement():
    """Verify that when status is BLOCKED, mutating API operations are blocked with 403."""
    # Simulate developer blocking system
    set_setting("license_status", "BLOCKED")
    set_setting("license_block_message", "Payment overdue. Contact 0316-6868169.")

    # 1. License status reports blocked
    res = client.get("/api/license/status")
    assert res.status_code == 200
    data = res.json()
    assert data["blocked"] is True
    assert "Payment overdue" in data["message"]

    # 2. Static and home page remain reachable so UI can show lock modal
    res_home = client.get("/")
    assert res_home.status_code == 200

    # 3. Mutating API endpoints (e.g. punching or adding advance) are rejected with 403
    res_punch = client.post("/api/punch", json={"staff_id": 1, "method": "PIN"})
    assert res_punch.status_code == 403
    punch_data = res_punch.json()
    assert punch_data.get("license_blocked") is True

def test_system_unblock_restoration():
    """Verify that restoring ACTIVE state immediately unblocks API endpoints."""
    # Start blocked
    set_setting("license_status", "BLOCKED")
    assert license_manager.is_system_blocked() is True

    # Restore active
    set_setting("license_status", "ACTIVE")
    assert license_manager.is_system_blocked() is False

    res = client.get("/api/license/status")
    assert res.status_code == 200
    assert res.json()["blocked"] is False

def test_license_config_update():
    """Verify configuring sheet URL and dev contact."""
    res = client.post("/api/license/config", json={
        "sheet_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv",
        "dev_contact": "0300-1122334"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert get_setting("license_dev_contact") == "0300-1122334"
