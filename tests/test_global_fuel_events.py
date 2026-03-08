"""Tests for global fuel events (corr_fuel_set, refill) always stored with generator_id='main'."""

import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("SQLITE_PATH", ":memory:")

import config
import database.models as db_models
from database.api.logs import (
    add_log,
    get_latest_corr_fuel_before,
    get_logs_for_period,
    get_refills_for_date,
)
from database.api.state import _conn_set_state_value
from database.models import get_connection


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch, tmp_path):
    """Fresh database for each test."""
    db_path = str(tmp_path / "test_global_events.db")
    monkeypatch.setattr(config, "SQLITE_PATH", db_path)
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite")
    db_models.init_db()
    yield


def _set_active_generator(gen_id: str):
    """Helper: set the active generator in state."""
    with get_connection() as conn:
        _conn_set_state_value(conn, "active_generator", gen_id)
        conn.commit()


def _get_log_generator_id(event_type: str) -> str | None:
    """Helper: return generator_id of the most recent log of a given event_type."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT generator_id FROM logs WHERE event_type = ? ORDER BY id DESC LIMIT 1",
            (event_type,),
        ).fetchone()
    return row[0] if row else None


class TestAddLogGlobalEvents:
    """add_log stores corr_fuel_set and refill with generator_id='main' always."""

    def test_corr_fuel_set_stored_as_main_when_active_is_main(self):
        _set_active_generator("main")
        add_log("corr_fuel_set", "user1", val="100.0")
        assert _get_log_generator_id("corr_fuel_set") == "main"

    def test_corr_fuel_set_stored_as_main_when_active_is_emergency(self):
        _set_active_generator("emergency")
        add_log("corr_fuel_set", "user1", val="80.0")
        assert _get_log_generator_id("corr_fuel_set") == "main"

    def test_refill_stored_as_main_when_active_is_main(self):
        _set_active_generator("main")
        add_log("refill", "user1", val="50.0")
        assert _get_log_generator_id("refill") == "main"

    def test_refill_stored_as_main_when_active_is_emergency(self):
        _set_active_generator("emergency")
        add_log("refill", "user1", val="50.0")
        assert _get_log_generator_id("refill") == "main"

    def test_non_global_event_uses_active_generator(self):
        _set_active_generator("emergency")
        add_log("m_start", "user1")
        assert _get_log_generator_id("m_start") == "emergency"

    def test_non_global_event_explicit_generator_id_respected(self):
        _set_active_generator("main")
        add_log("m_start", "user1", generator_id="emergency")
        assert _get_log_generator_id("m_start") == "emergency"


class TestGetLogsForPeriodGlobalEvents:
    """get_logs_for_period always returns global events regardless of generator_id filter."""

    def test_corr_fuel_set_visible_to_main_even_if_logged_during_emergency(self):
        # Simulate: corr_fuel_set stored with generator_id='main' (new behaviour)
        # but report is requested for 'main' — should always be visible
        add_log("corr_fuel_set", "user1", val="100.0", ts="2026-03-05 10:00:00")
        add_log("m_start", "user1", ts="2026-03-05 08:00:00", generator_id="main")

        logs = get_logs_for_period("2026-03-01", "2026-03-31", generator_id="main")
        event_types = [r[0] for r in logs]
        assert "corr_fuel_set" in event_types

    def test_refill_visible_to_main_report(self):
        add_log("refill", "user1", val="50.0", ts="2026-03-05 12:00:00")
        logs = get_logs_for_period("2026-03-01", "2026-03-31", generator_id="main")
        event_types = [r[0] for r in logs]
        assert "refill" in event_types

    def test_corr_fuel_set_visible_to_emergency_report(self):
        # corr_fuel_set is stored as 'main' but emergency report should also see it
        add_log("corr_fuel_set", "user1", val="100.0", ts="2026-03-05 10:00:00")
        add_log("e_start", "user1", ts="2026-03-05 08:00:00", generator_id="emergency")

        logs = get_logs_for_period("2026-03-01", "2026-03-31", generator_id="emergency")
        event_types = [r[0] for r in logs]
        assert "corr_fuel_set" in event_types

    def test_refill_visible_to_emergency_report(self):
        add_log("refill", "user1", val="50.0", ts="2026-03-05 12:00:00")
        logs = get_logs_for_period("2026-03-01", "2026-03-31", generator_id="emergency")
        event_types = [r[0] for r in logs]
        assert "refill" in event_types

    def test_non_global_event_filtered_by_generator_id(self):
        add_log("m_start", "user1", ts="2026-03-05 08:00:00", generator_id="main")
        add_log("e_start", "user1", ts="2026-03-05 09:00:00", generator_id="emergency")

        main_logs = get_logs_for_period("2026-03-01", "2026-03-31", generator_id="main")
        main_events = [r[0] for r in main_logs]
        assert "m_start" in main_events
        assert "e_start" not in main_events


class TestGetRefillsForDateGlobalEvent:
    """get_refills_for_date returns refills regardless of generator_id argument."""

    def test_refills_returned_ignoring_generator_id_filter(self):
        # Store a refill (will be stored as 'main' due to global event logic)
        add_log("refill", "user1", val="60.0", ts="2026-03-10 14:00:00")

        # Requesting with generator_id='emergency' should still return the refill
        rows = get_refills_for_date("2026-03-10", generator_id="emergency")
        assert len(rows) == 1
        assert float(rows[0][2]) == 60.0

    def test_refills_returned_for_main_generator_id(self):
        add_log("refill", "user1", val="40.0", ts="2026-03-15 10:00:00")

        rows = get_refills_for_date("2026-03-15", generator_id="main")
        assert len(rows) == 1

    def test_no_refills_returns_empty(self):
        rows = get_refills_for_date("2026-03-20", generator_id="main")
        assert rows == []


class TestGetLatestCorrFuelBeforeGlobalEvent:
    """get_latest_corr_fuel_before ignores generator_id — corr_fuel_set is global."""

    def test_finds_correction_regardless_of_generator_id_argument(self):
        # Insert a corr_fuel_set directly with generator_id='main' (normal path)
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, generator_id)"
                " VALUES ('corr_fuel_set', '2026-02-20 10:00:00', 'user1', '120.0', 'main')"
            )
            conn.commit()

        # Should find it even when generator_id='emergency' is passed
        result = get_latest_corr_fuel_before("2026-03-01 00:00:00", generator_id="emergency")
        assert result == 120.0

    def test_finds_most_recent_correction_before_ts(self):
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, generator_id)"
                " VALUES ('corr_fuel_set', '2026-02-10 10:00:00', 'user1', '90.0', 'main')"
            )
            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, generator_id)"
                " VALUES ('corr_fuel_set', '2026-02-25 10:00:00', 'user1', '130.0', 'main')"
            )
            conn.commit()

        result = get_latest_corr_fuel_before("2026-03-01 00:00:00")
        assert result == 130.0

    def test_returns_none_when_no_correction_before_ts(self):
        result = get_latest_corr_fuel_before("2026-01-01 00:00:00")
        assert result is None


class TestInitDbMigration:
    """init_db migrates existing corr_fuel_set/refill records to generator_id='main'."""

    def test_existing_records_with_wrong_generator_id_are_fixed(self, monkeypatch, tmp_path):
        # Create a fresh DB with wrong data, then re-run init_db
        db_path = str(tmp_path / "migration_test.db")
        monkeypatch.setattr(config, "SQLITE_PATH", db_path)
        monkeypatch.setattr(config, "DB_BACKEND", "sqlite")

        db_models.init_db()

        # Manually insert records with wrong generator_id (simulating old data)
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, generator_id)"
                " VALUES ('corr_fuel_set', '2026-01-15 10:00:00', 'user1', '80.0', 'emergency')"
            )
            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, generator_id)"
                " VALUES ('refill', '2026-01-20 12:00:00', 'user1', '50.0', 'emergency')"
            )
            conn.commit()

        # Re-run init_db to trigger migration
        db_models.init_db()

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT event_type, generator_id FROM logs WHERE event_type IN ('corr_fuel_set', 'refill')"
            ).fetchall()

        for event_type, gen_id in rows:
            assert gen_id == "main", f"{event_type} still has generator_id='{gen_id}'"
