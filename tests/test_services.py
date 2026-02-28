"""Tests for app/services/* — GeneratorService, FuelService, ShiftService."""

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("SQLITE_PATH", ":memory:")

import config
import database.models as db_models
from app.repositories.fuel_repo import FuelRepository
from app.repositories.generator_repo import GeneratorRepository
from app.repositories.shift_repo import ShiftRepository
from app.services.fuel_service import FuelService
from app.services.generator_service import GeneratorService
from app.services.shift_service import ShiftService


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch, tmp_path):
    """Fresh in-memory database for each test."""
    db_path = str(tmp_path / "test_services.db")
    monkeypatch.setattr(config, "SQLITE_PATH", db_path)
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite")
    db_models.init_db()
    yield


# ---------------------------------------------------------------------------
# GeneratorService
# ---------------------------------------------------------------------------


class TestGeneratorService:
    def _make(self):
        return GeneratorService(GeneratorRepository())

    def test_get_active_generator_returns_string(self):
        svc = self._make()
        result = svc.get_active_generator()
        assert isinstance(result, str)
        assert result in ("main", "emergency")

    def test_get_stats_returns_dict(self):
        svc = self._make()
        stats = svc.get_stats()
        assert isinstance(stats, dict)

    def test_get_stats_explicit_generator(self):
        svc = self._make()
        stats = svc.get_stats("main")
        assert isinstance(stats, dict)

    def test_get_name_returns_string(self):
        svc = self._make()
        name = svc.get_name()
        assert isinstance(name, str)

    def test_is_emergency_active_returns_bool(self):
        svc = self._make()
        result = svc.is_emergency_active()
        assert isinstance(result, bool)

    def test_switch_generator_returns_tuple(self):
        svc = self._make()
        ok, msg = svc.switch_generator("emergency", admin_name="test_admin")
        assert isinstance(ok, bool)
        assert isinstance(msg, str)


# ---------------------------------------------------------------------------
# FuelService
# ---------------------------------------------------------------------------


class TestFuelService:
    def _make(self):
        return FuelService(FuelRepository())

    def test_get_consumption_rate_returns_float(self):
        svc = self._make()
        rate = svc.get_consumption_rate()
        assert isinstance(rate, float)
        assert rate >= 0

    def test_get_current_level_returns_float(self):
        svc = self._make()
        level = svc.get_current_level()
        assert isinstance(level, float)

    def test_refuel_positive_amount(self):
        svc = self._make()
        before = svc.get_current_level()
        svc.refuel(10.0)
        after = svc.get_current_level()
        assert after == pytest.approx(before + 10.0, abs=0.1)

    def test_refuel_raises_on_non_positive(self):
        svc = self._make()
        with pytest.raises(ValueError):
            svc.refuel(0)
        with pytest.raises(ValueError):
            svc.refuel(-5.0)

    def test_consume_raises_on_non_positive(self):
        svc = self._make()
        with pytest.raises(ValueError):
            svc.consume(0)
        with pytest.raises(ValueError):
            svc.consume(-1.0)


# ---------------------------------------------------------------------------
# ShiftService
# ---------------------------------------------------------------------------


class TestShiftService:
    def _make(self):
        return ShiftService(ShiftRepository())

    def test_get_today_completed_returns_list(self):
        svc = self._make()
        result = svc.get_today_completed()
        assert isinstance(result, list)

    def test_get_recent_events_returns_list(self):
        svc = self._make()
        result = svc.get_recent_events()
        assert isinstance(result, list)

    def test_start_and_stop_shift(self):
        svc = self._make()
        now = datetime.now()

        start_result = svc.start_shift("START", "test_user", now)
        assert isinstance(start_result, dict)
        assert "ok" in start_result

        if start_result["ok"]:
            stop_result = svc.stop_shift("STOP", "test_user", now)
            assert isinstance(stop_result, dict)
            assert "ok" in stop_result


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------


class TestContainer:
    def test_container_initialises(self):
        from app.container import Container

        c = Container()
        assert isinstance(c.generator_service, GeneratorService)
        assert isinstance(c.fuel_service, FuelService)
        assert isinstance(c.shift_service, ShiftService)

    def test_container_repos_wired(self):
        from app.container import Container

        c = Container()
        assert isinstance(c.generator_repo, GeneratorRepository)
        assert isinstance(c.fuel_repo, FuelRepository)
        assert isinstance(c.shift_repo, ShiftRepository)


# ---------------------------------------------------------------------------
# GoogleSheetsClient
# ---------------------------------------------------------------------------


class TestGoogleSheetsClient:
    def test_is_available_false_when_no_sheet_id(self, monkeypatch):
        monkeypatch.setattr(config, "SHEET_ID", None, raising=False)
        from app.integrations.google_sheets import GoogleSheetsClient

        client = GoogleSheetsClient(sheet_id=None)
        assert client.is_available() is False

    def test_is_available_false_when_no_creds_file(self, tmp_path):
        from app.integrations.google_sheets import GoogleSheetsClient

        client = GoogleSheetsClient(
            service_account_path=str(tmp_path / "missing.json"),
            sheet_id="some_id",
        )
        assert client.is_available() is False

    def test_is_available_true_when_both_present(self, tmp_path):
        creds = tmp_path / "sa.json"
        creds.write_text("{}")
        from app.integrations.google_sheets import GoogleSheetsClient

        client = GoogleSheetsClient(
            service_account_path=str(creds),
            sheet_id="some_id",
        )
        assert client.is_available() is True

    def test_get_client_raises_when_file_missing(self):
        from app.integrations.google_sheets import GoogleSheetsClient

        client = GoogleSheetsClient(
            service_account_path="/nonexistent/path.json",
            sheet_id="some_id",
        )
        with pytest.raises(RuntimeError, match="Service account file not found"):
            client.get_client()

    def test_get_spreadsheet_raises_when_no_sheet_id(self):
        from app.integrations.google_sheets import GoogleSheetsClient

        client = GoogleSheetsClient(sheet_id=None)
        with pytest.raises(RuntimeError, match="SHEET_ID is not configured"):
            client.get_spreadsheet()
