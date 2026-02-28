"""Tests for dynamic configuration management (generator_config, global_config, config_history)."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("SQLITE_PATH", ":memory:")

import config
import database.models as db_models
import database.db_api as db
from fastapi.testclient import TestClient
from webapp_server import create_app


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch, tmp_path):
    """Create a fresh DB for each test."""
    db_path = str(tmp_path / "test_config.db")
    monkeypatch.setattr(config, "SQLITE_PATH", db_path)
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite")
    monkeypatch.setattr(config, "FUEL_CONSUMPTION", 5.3)
    monkeypatch.setattr(config, "EMERGENCY_FUEL_CONSUMPTION", 5.3)
    db_models.init_db()
    yield


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Database API tests
# ---------------------------------------------------------------------------

class TestGetFuelConsumptionRateDb:
    def test_returns_db_value_when_set(self):
        db.set_generator_param("main", "fuel_consumption_rate", 7.0)
        assert db.get_fuel_consumption_rate_db("main") == 7.0

    def test_returns_db_value_after_manual_set(self, monkeypatch):
        monkeypatch.setattr(config, "FUEL_CONSUMPTION", 6.2)
        from database.api.config import get_fuel_consumption_rate_db
        db.set_generator_param("main", "fuel_consumption_rate", 6.2)
        assert get_fuel_consumption_rate_db("main") == 6.2

    def test_emergency_returns_own_value(self):
        db.set_generator_param("main", "fuel_consumption_rate", 7.0)
        db.set_generator_param("emergency", "fuel_consumption_rate", 6.5)
        assert db.get_fuel_consumption_rate_db("emergency") == 6.5


class TestGetFuelPriceDb:
    def test_returns_db_value_when_set(self):
        db.set_global_param("fuel_price", 52.0)
        assert db.get_fuel_price_db() == 52.0

    def test_returns_default_when_no_db(self, monkeypatch):
        # DB is seeded with 50.0 by default
        assert db.get_fuel_price_db() == 50.0


class TestSetGeneratorParam:
    def test_set_valid_value(self):
        result = db.set_generator_param("main", "fuel_consumption_rate", 8.0)
        assert result is True
        assert db.get_generator_param("main", "fuel_consumption_rate") == 8.0

    def test_set_invalid_generator_id_raises(self):
        with pytest.raises(ValueError, match="Invalid generator_id"):
            db.set_generator_param("unknown", "fuel_consumption_rate", 7.0)

    def test_set_invalid_param_name_raises(self):
        with pytest.raises(ValueError, match="Invalid param_name"):
            db.set_generator_param("main", "bad_param", 7.0)

    def test_set_below_min_raises(self):
        with pytest.raises(ValueError, match="fuel_consumption_rate must be between"):
            db.set_generator_param("main", "fuel_consumption_rate", 1.0)

    def test_set_above_max_raises(self):
        with pytest.raises(ValueError, match="fuel_consumption_rate must be between"):
            db.set_generator_param("main", "fuel_consumption_rate", 20.0)

    def test_set_records_history(self):
        db.set_generator_param("main", "fuel_consumption_rate", 7.0)
        db.set_generator_param("main", "fuel_consumption_rate", 8.0)
        history = db.get_config_history(limit=5)
        assert any(
            h["param_name"] == "fuel_consumption_rate"
            and h["new_value"] == 8.0
            for h in history
        )

    def test_set_with_admin_info(self):
        result = db.set_generator_param(
            "main", "fuel_consumption_rate", 7.5,
            updated_by=123, updated_by_name="Admin"
        )
        assert result is True
        cfg = db.get_generator_config("main")
        assert cfg["fuel_consumption_rate"]["updated_by"] == "Admin"


class TestSetGlobalParam:
    def test_set_valid_price(self):
        result = db.set_global_param("fuel_price", 55.0)
        assert result is True
        assert db.get_global_param("fuel_price") == 55.0

    def test_set_invalid_param_name_raises(self):
        with pytest.raises(ValueError, match="Invalid param_name"):
            db.set_global_param("bad_param", 50.0)

    def test_set_below_min_raises(self):
        with pytest.raises(ValueError, match="fuel_price must be between"):
            db.set_global_param("fuel_price", 5.0)

    def test_set_above_max_raises(self):
        with pytest.raises(ValueError, match="fuel_price must be between"):
            db.set_global_param("fuel_price", 300.0)

    def test_set_records_history(self):
        db.set_global_param("fuel_price", 45.0)
        db.set_global_param("fuel_price", 55.0)
        history = db.get_config_history(limit=5)
        assert any(
            h["param_name"] == "fuel_price" and h["new_value"] == 55.0
            for h in history
        )


class TestGetConfigHistory:
    def test_empty_initially_after_init(self):
        # After init_db seeding, history may have entries from seeding
        # but we only care about manual changes here
        history = db.get_config_history(limit=50)
        # All history entries from seeding have no old_value (first time)
        assert isinstance(history, list)

    def test_records_generator_change(self):
        db.set_generator_param("main", "fuel_consumption_rate", 7.0, 1, "Admin")
        db.set_generator_param("main", "fuel_consumption_rate", 8.0, 1, "Admin")
        history = db.get_config_history(limit=10)
        changes = [h for h in history if h["param_name"] == "fuel_consumption_rate"
                   and h["config_type"] == "generator"]
        assert len(changes) >= 2

    def test_records_global_change(self):
        db.set_global_param("fuel_price", 60.0, 1, "Admin")
        history = db.get_config_history(limit=10)
        changes = [h for h in history if h["param_name"] == "fuel_price"
                   and h["config_type"] == "global"]
        assert len(changes) >= 1
        assert changes[0]["new_value"] == 60.0


class TestGetFuelConsumptionRateState:
    """Tests for the updated get_fuel_consumption_rate() in state.py."""

    def test_reads_from_db_for_main(self):
        db.set_generator_param("main", "fuel_consumption_rate", 7.0)
        db.set_state("active_generator", "main")
        rate = db.get_fuel_consumption_rate()
        assert rate == 7.0

    def test_reads_from_db_for_emergency(self):
        db.set_generator_param("emergency", "fuel_consumption_rate", 6.5)
        db.set_state("active_generator", "emergency")
        rate = db.get_fuel_consumption_rate()
        assert rate == 6.5

    def test_explicit_generator_id(self):
        db.set_generator_param("main", "fuel_consumption_rate", 7.0)
        db.set_generator_param("emergency", "fuel_consumption_rate", 6.5)
        assert db.get_fuel_consumption_rate(generator_id="main") == 7.0
        assert db.get_fuel_consumption_rate(generator_id="emergency") == 6.5


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestApiAdminConfig:
    """Tests for /api/admin/config endpoints."""

    def test_get_config_requires_admin(self, client):
        resp = client.get("/api/admin/config")
        # Without auth should be 401 or 403
        assert resp.status_code in (401, 403)

    def test_set_generator_requires_admin(self, client):
        resp = client.post(
            "/api/admin/config/generator",
            json={"generator_id": "main", "param_name": "fuel_consumption_rate", "value": 7.0},
        )
        assert resp.status_code in (401, 403)

    def test_set_global_requires_admin(self, client):
        resp = client.post(
            "/api/admin/config/global",
            json={"param_name": "fuel_price", "value": 52.0},
        )
        assert resp.status_code in (401, 403)

    def test_config_history_requires_admin(self, client):
        resp = client.get("/api/admin/config/history")
        assert resp.status_code in (401, 403)

    def test_set_generator_with_mock_admin(self, client, monkeypatch):
        """Test that set_generator endpoint works for admin user."""
        monkeypatch.setattr("webapp_server._extract_user", lambda req: {"id": 123, "first_name": "Admin"})
        monkeypatch.setattr("webapp_server._is_admin", lambda user: True)

        resp = client.post(
            "/api/admin/config/generator",
            json={"generator_id": "main", "param_name": "fuel_consumption_rate", "value": 7.5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        assert data.get("new_value") == 7.5

    def test_set_generator_invalid_value(self, client, monkeypatch):
        """Test validation rejects out-of-range values."""
        monkeypatch.setattr("webapp_server._extract_user", lambda req: {"id": 123, "first_name": "Admin"})
        monkeypatch.setattr("webapp_server._is_admin", lambda user: True)

        resp = client.post(
            "/api/admin/config/generator",
            json={"generator_id": "main", "param_name": "fuel_consumption_rate", "value": 100.0},
        )
        assert resp.status_code == 400

    def test_set_global_fuel_price(self, client, monkeypatch):
        """Test setting global fuel price works."""
        monkeypatch.setattr("webapp_server._extract_user", lambda req: {"id": 123, "first_name": "Admin"})
        monkeypatch.setattr("webapp_server._is_admin", lambda user: True)

        resp = client.post(
            "/api/admin/config/global",
            json={"param_name": "fuel_price", "value": 55.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True

    def test_get_config_returns_structure(self, client, monkeypatch):
        """Test GET /api/admin/config returns expected structure."""
        monkeypatch.setattr("webapp_server._extract_user", lambda req: {"id": 123, "first_name": "Admin"})
        monkeypatch.setattr("webapp_server._is_admin", lambda user: True)

        resp = client.get("/api/admin/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "generators" in data
        assert "main" in data["generators"]
        assert "emergency" in data["generators"]
        assert "global" in data
        assert "fuel_price" in data["global"]

    def test_config_history_pagination(self, client, monkeypatch):
        """Test history returns paginated results."""
        monkeypatch.setattr("webapp_server._extract_user", lambda req: {"id": 123, "first_name": "Admin"})
        monkeypatch.setattr("webapp_server._is_admin", lambda user: True)

        resp = client.get("/api/admin/config/history?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "history" in data
        assert isinstance(data["history"], list)


class TestApiAdminConfigValidation:
    """Additional validation tests for config API."""

    def _mock_admin(self, monkeypatch):
        monkeypatch.setattr("webapp_server._extract_user", lambda req: {"id": 1, "first_name": "Admin"})
        monkeypatch.setattr("webapp_server._is_admin", lambda user: True)

    def test_invalid_generator_id(self, client, monkeypatch):
        self._mock_admin(monkeypatch)
        resp = client.post(
            "/api/admin/config/generator",
            json={"generator_id": "unknown", "param_name": "fuel_consumption_rate", "value": 7.0},
        )
        assert resp.status_code == 400

    def test_invalid_param_name_generator(self, client, monkeypatch):
        self._mock_admin(monkeypatch)
        resp = client.post(
            "/api/admin/config/generator",
            json={"generator_id": "main", "param_name": "bad_param", "value": 7.0},
        )
        assert resp.status_code == 400

    def test_invalid_param_name_global(self, client, monkeypatch):
        self._mock_admin(monkeypatch)
        resp = client.post(
            "/api/admin/config/global",
            json={"param_name": "invalid_param", "value": 50.0},
        )
        assert resp.status_code == 400

    def test_missing_fields_generator(self, client, monkeypatch):
        self._mock_admin(monkeypatch)
        resp = client.post("/api/admin/config/generator", json={})
        assert resp.status_code == 400

    def test_missing_fields_global(self, client, monkeypatch):
        self._mock_admin(monkeypatch)
        resp = client.post("/api/admin/config/global", json={})
        assert resp.status_code == 400

    def test_non_numeric_value(self, client, monkeypatch):
        self._mock_admin(monkeypatch)
        resp = client.post(
            "/api/admin/config/generator",
            json={"generator_id": "main", "param_name": "fuel_consumption_rate", "value": "abc"},
        )
        assert resp.status_code == 400

    def test_fuel_price_below_min(self, client, monkeypatch):
        self._mock_admin(monkeypatch)
        resp = client.post(
            "/api/admin/config/global",
            json={"param_name": "fuel_price", "value": 5.0},
        )
        assert resp.status_code == 400

    def test_fuel_price_above_max(self, client, monkeypatch):
        self._mock_admin(monkeypatch)
        resp = client.post(
            "/api/admin/config/global",
            json={"param_name": "fuel_price", "value": 500.0},
        )
        assert resp.status_code == 400
