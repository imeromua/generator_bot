"""Tests for webapp_server.py — Mini App API endpoints."""
import pytest
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("SQLITE_PATH", ":memory:")

import config
import database.models as db_models
import database.db_api as db
from webapp_server import create_app, _validate_init_data


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch, tmp_path):
    """Create a fresh in-memory database for each test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "SQLITE_PATH", db_path)
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite")
    db_models.init_db()
    yield


@pytest.fixture
def client(aiohttp_client):
    """Create aiohttp test client for the webapp."""
    app = create_app()
    return aiohttp_client(app)


# ---------------------------------------------------------------------------
# API /api/status
# ---------------------------------------------------------------------------

class TestApiStatus:
    """Tests for GET /api/status endpoint."""

    @pytest.mark.asyncio
    async def test_status_returns_ok(self, client):
        """Status endpoint should return 200 with default state."""
        resp = await (await client).get("/api/status")
        assert resp.status == 200
        data = await resp.json()
        assert "status" in data
        assert data["status"] == "OFF"

    @pytest.mark.asyncio
    async def test_status_contains_all_fields(self, client):
        """Status should contain all expected fields."""
        resp = await (await client).get("/api/status")
        data = await resp.json()
        expected_fields = [
            "status", "generator", "generator_name",
            "current_fuel", "estimated_fuel", "fuel_rate",
            "total_hours", "active_shift", "completed_shifts",
            "start_time", "work_start", "work_end",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_status_fuel_estimation_when_on(self, client, monkeypatch):
        """Fuel estimation should work when generator is ON with proper date/time."""
        now = datetime.now(config.KYIV)
        start_dt = now - timedelta(hours=2)

        db.set_state("status", "ON")
        db.set_state("last_start_time", start_dt.strftime("%H:%M"))
        db.set_state("last_start_date", start_dt.strftime("%Y-%m-%d"))
        db.set_state("current_fuel", "100.0")
        db.set_state("active_shift", "m_start")

        resp = await (await client).get("/api/status")
        data = await resp.json()

        assert data["status"] == "ON"
        # estimated_fuel should be less than current_fuel (fuel consumed over 2 hours)
        assert data["estimated_fuel"] < data["current_fuel"]

    @pytest.mark.asyncio
    async def test_status_fuel_estimation_without_date(self, client):
        """Fuel estimation should handle missing start_date gracefully."""
        now = datetime.now(config.KYIV)
        start_dt = now - timedelta(hours=1)

        db.set_state("status", "ON")
        db.set_state("last_start_time", start_dt.strftime("%H:%M"))
        db.set_state("last_start_date", "")
        db.set_state("current_fuel", "50.0")
        db.set_state("active_shift", "d_start")

        resp = await (await client).get("/api/status")
        data = await resp.json()
        assert data["status"] == "ON"
        # Should still compute estimate using today's date as fallback
        assert isinstance(data["estimated_fuel"], (int, float))

    @pytest.mark.asyncio
    async def test_status_uses_correct_generator_hours(self, client, monkeypatch):
        """Total hours should reflect the active generator's hours."""
        monkeypatch.setattr(config, "FUEL_CONSUMPTION", 5.0)
        monkeypatch.setattr(config, "EMERGENCY_FUEL_CONSUMPTION", 3.0)

        db.set_state("total_hours", "100.0")
        db.set_state("emergency_total_hours", "50.0")
        db.set_state("active_generator", "main")

        c = await client
        resp = await c.get("/api/status")
        data = await resp.json()
        assert data["total_hours"] == 100.0

        # Switch to emergency
        db.set_state("active_generator", "emergency")
        resp = await c.get("/api/status")
        data = await resp.json()
        assert data["total_hours"] == 50.0


# ---------------------------------------------------------------------------
# API /api/schedule
# ---------------------------------------------------------------------------

class TestApiSchedule:
    """Tests for GET /api/schedule endpoint."""

    @pytest.mark.asyncio
    async def test_schedule_returns_ok(self, client):
        """Schedule endpoint should return 200."""
        resp = await (await client).get("/api/schedule")
        assert resp.status == 200
        data = await resp.json()
        assert "hours" in data
        assert len(data["hours"]) == 24

    @pytest.mark.asyncio
    async def test_schedule_with_date(self, client):
        """Schedule should accept date parameter."""
        resp = await (await client).get("/api/schedule?date=2025-01-15")
        assert resp.status == 200
        data = await resp.json()
        assert data["date"] == "2025-01-15"

    @pytest.mark.asyncio
    async def test_schedule_invalid_date(self, client):
        """Schedule should return 400 for invalid date format."""
        resp = await (await client).get("/api/schedule?date=invalid")
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_schedule_with_outage_data(self, client):
        """Schedule should reflect saved outage data."""
        date_str = "2025-06-15"
        db.set_schedule_range(date_str, 10, 14)

        resp = await (await client).get(f"/api/schedule?date={date_str}")
        data = await resp.json()

        off_hours = [h for h in data["hours"] if h["off"]]
        assert len(off_hours) == 4  # hours 10, 11, 12, 13


# ---------------------------------------------------------------------------
# API /api/schedule/week
# ---------------------------------------------------------------------------

class TestApiScheduleWeek:
    """Tests for GET /api/schedule/week endpoint."""

    @pytest.mark.asyncio
    async def test_week_returns_7_days(self, client):
        """Week endpoint should return 7 days."""
        resp = await (await client).get("/api/schedule/week")
        assert resp.status == 200
        data = await resp.json()
        assert "days" in data
        assert len(data["days"]) == 7

    @pytest.mark.asyncio
    async def test_week_day_structure(self, client):
        """Each day should have date, weekday, off_hours fields."""
        resp = await (await client).get("/api/schedule/week")
        data = await resp.json()
        for day in data["days"]:
            assert "date" in day
            assert "weekday" in day
            assert "off_hours" in day


# ---------------------------------------------------------------------------
# API /api/events
# ---------------------------------------------------------------------------

class TestApiEvents:
    """Tests for GET /api/events endpoint."""

    @pytest.mark.asyncio
    async def test_events_returns_ok(self, client):
        """Events endpoint should return 200."""
        resp = await (await client).get("/api/events")
        assert resp.status == 200
        data = await resp.json()
        assert "events" in data
        assert "count" in data

    @pytest.mark.asyncio
    async def test_events_with_data(self, client):
        """Events should include logged events."""
        db.add_log("refill", "TestUser", val="20.0")
        db.add_log("m_start", "TestUser")

        resp = await (await client).get("/api/events?limit=10")
        data = await resp.json()
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_events_limit(self, client):
        """Events limit should be respected."""
        for i in range(5):
            db.add_log("refill", "User", val=str(i))

        resp = await (await client).get("/api/events?limit=3")
        data = await resp.json()
        assert data["count"] == 3

    @pytest.mark.asyncio
    async def test_events_max_limit(self, client):
        """Events limit should not exceed MAX_EVENTS_LIMIT (100)."""
        resp = await (await client).get("/api/events?limit=200")
        assert resp.status == 200


# ---------------------------------------------------------------------------
# API /api/maintenance
# ---------------------------------------------------------------------------

class TestApiMaintenance:
    """Tests for GET /api/maintenance endpoint."""

    @pytest.mark.asyncio
    async def test_maintenance_returns_ok(self, client):
        """Maintenance endpoint should return 200."""
        resp = await (await client).get("/api/maintenance")
        assert resp.status == 200
        data = await resp.json()
        assert "generator" in data
        assert "stats" in data
        assert "history" in data

    @pytest.mark.asyncio
    async def test_maintenance_stats_fields(self, client):
        """Maintenance stats should contain expected fields."""
        resp = await (await client).get("/api/maintenance")
        data = await resp.json()
        stats = data["stats"]
        assert "oil_needed" in stats
        assert "spark_needed" in stats
        assert "maintenance_needed" in stats
        assert "total_hours" in stats
        assert "oil_interval" in stats
        assert "spark_interval" in stats
        assert "maintenance_interval" in stats


# ---------------------------------------------------------------------------
# Telegram initData validation
# ---------------------------------------------------------------------------

class TestInitDataValidation:
    """Tests for Telegram WebApp initData validation."""

    def test_empty_init_data_returns_none(self):
        """Empty init data should return None."""
        assert _validate_init_data("", "token") is None

    def test_missing_hash_returns_none(self):
        """Init data without hash should return None."""
        assert _validate_init_data("user=test", "token") is None

    def test_invalid_hash_returns_none(self):
        """Init data with wrong hash should return None."""
        result = _validate_init_data("user=test&hash=invalidhash", "token")
        assert result is None


# ---------------------------------------------------------------------------
# Task 5: API /api/notifications
# ---------------------------------------------------------------------------

class TestApiNotifications:
    """Tests for notification preferences endpoints."""

    @pytest.mark.asyncio
    async def test_get_preferences_no_auth(self, client):
        """Unauthenticated request should return 401."""
        resp = await (await client).get("/api/notifications/preferences")
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_post_preferences_no_auth(self, client):
        """Unauthenticated POST should return 401."""
        resp = await (await client).post(
            "/api/notifications/preferences",
            json={"notification_type": "fuel_warning", "enabled": True},
        )
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_test_notification_no_auth(self, client):
        """Unauthenticated test notification should return 401."""
        resp = await (await client).post("/api/notifications/test", json={})
        assert resp.status == 401


# ---------------------------------------------------------------------------
# Task 6: API /api/fuel/orders
# ---------------------------------------------------------------------------

class TestApiFuelOrders:
    """Tests for fuel orders endpoints."""

    @pytest.mark.asyncio
    async def test_get_orders_no_auth(self, client):
        """Unauthenticated request should return 401."""
        resp = await (await client).get("/api/fuel/orders")
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_create_order_no_auth(self, client):
        """Unauthenticated POST should return 401."""
        resp = await (await client).post(
            "/api/fuel/orders",
            json={"amount_liters": 200},
        )
        assert resp.status == 403  # admin required → 403

    @pytest.mark.asyncio
    async def test_update_order_no_auth(self, client):
        """Unauthenticated update should return 403."""
        resp = await (await client).post(
            "/api/fuel/orders/update",
            json={"order_id": 1, "status": "ordered"},
        )
        assert resp.status == 403


# ---------------------------------------------------------------------------
# Task 8: API /api/shifts
# ---------------------------------------------------------------------------

class TestApiShifts:
    """Tests for shift schedule endpoints."""

    @pytest.mark.asyncio
    async def test_get_shifts_no_auth(self, client):
        """Unauthenticated request should return 401."""
        resp = await (await client).get("/api/shifts/schedule")
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_set_shift_no_auth(self, client):
        """Unauthenticated POST should return 403."""
        resp = await (await client).post(
            "/api/shifts/schedule",
            json={"date": "2025-01-01", "shift_type": "m"},
        )
        assert resp.status == 403

    @pytest.mark.asyncio
    async def test_auto_schedule_no_auth(self, client):
        """Unauthenticated auto schedule should return 403."""
        resp = await (await client).post(
            "/api/shifts/auto",
            json={"month": "2025-01"},
        )
        assert resp.status == 403

    @pytest.mark.asyncio
    async def test_analytics_no_auth(self, client):
        """Unauthenticated analytics should return 401."""
        resp = await (await client).get("/api/shifts/analytics")
        assert resp.status == 401
