"""Tests for notification reliability fixes and daily report improvements.

Covers:
- Daily report recipient selection (admins must receive it too)
- Admin NOT excluded from daily report
- Quiet-hours midnight wrap-around fix
- Daily/weekly report window (MORNING_BRIEF_TIME-based)
- Daily report content blocks (generator, separate maintenance countdowns)
- Persistent idempotent send state (DB-based)
- Regression: missed notification scenario due to admin filtering
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
from zoneinfo import ZoneInfo

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("SQLITE_PATH", ":memory:")

import config
import database.models as db_models
import database.db_api as db


# ---------------------------------------------------------------------------
# DB setup fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch, tmp_path):
    """Fresh in-memory database for each test."""
    db_path = str(tmp_path / "test_notifications.db")
    monkeypatch.setattr(config, "SQLITE_PATH", db_path)
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite")
    db_models.init_db()
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KYIV = ZoneInfo("Europe/Kyiv")


def _make_dt(hour: int, minute: int = 0, tz=KYIV) -> datetime:
    return datetime(2024, 1, 15, hour, minute, 0, tzinfo=tz)


# ---------------------------------------------------------------------------
# A. Daily report recipient selection — admins MUST receive the report
# ---------------------------------------------------------------------------


class TestDailyReportRecipients:
    """Daily report must be sent to all registered users, including admins."""

    def _make_bot(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(chat=MagicMock(id=1), message_id=1))
        return bot

    def _register_users(self, admin_id: int, user_id: int):
        """Register both admin and regular user in the DB."""
        db.register_user(admin_id, "Admin User")
        db.register_user(user_id, "Regular User")

    @pytest.mark.asyncio
    async def test_admin_receives_daily_report(self, monkeypatch):
        """Regression: admin must NOT be skipped in daily report dispatch."""
        admin_id = 111
        user_id = 222
        monkeypatch.setattr(config, "ADMIN_IDS", [admin_id])
        self._register_users(admin_id, user_id)

        bot = self._make_bot()

        now = _make_dt(7, 31)  # 1 minute after default 07:30 brief time
        monkeypatch.setattr(config, "MORNING_BRIEF_TIME", "07:30")

        from services.scheduler_parts.notification_check import check_all_notifications

        state = {"status": "OFF", "current_fuel": "200.0"}

        with (
            patch("services.scheduler_parts.notification_check.now_kiev", return_value=now),
            patch("services.scheduler_parts.notification_check._build_daily_report_text", return_value="test report"),
        ):
            await check_all_notifications(bot, state)

        sent_ids = {c.kwargs.get("chat_id") or c.args[0] for c in bot.send_message.call_args_list}
        assert admin_id in sent_ids, f"Admin {admin_id} must receive daily report (was skipped)"
        assert user_id in sent_ids, f"Regular user {user_id} must receive daily report"

    @pytest.mark.asyncio
    async def test_all_users_receive_daily_report_regardless_of_admin_status(self, monkeypatch):
        """Daily report is sent to all registered users, not filtered by ADMIN_IDS."""
        admin_id1 = 101
        admin_id2 = 102
        user_id1 = 201
        user_id2 = 202
        monkeypatch.setattr(config, "ADMIN_IDS", [admin_id1, admin_id2])

        for uid, name in [(admin_id1, "A1"), (admin_id2, "A2"), (user_id1, "U1"), (user_id2, "U2")]:
            db.register_user(uid, name)

        bot = self._make_bot()
        now = _make_dt(7, 35)
        monkeypatch.setattr(config, "MORNING_BRIEF_TIME", "07:30")

        from services.scheduler_parts.notification_check import check_all_notifications

        state = {"status": "OFF", "current_fuel": "200.0"}

        with (
            patch("services.scheduler_parts.notification_check.now_kiev", return_value=now),
            patch("services.scheduler_parts.notification_check._build_daily_report_text", return_value="report"),
        ):
            await check_all_notifications(bot, state)

        sent_ids = {c.kwargs.get("chat_id") or c.args[0] for c in bot.send_message.call_args_list}
        for uid in (admin_id1, admin_id2, user_id1, user_id2):
            assert uid in sent_ids, f"User {uid} should have received the daily report"

    @pytest.mark.asyncio
    async def test_daily_report_not_sent_outside_window(self, monkeypatch):
        """Daily report must not be sent when current time is before the window."""
        db.register_user(100, "user")
        monkeypatch.setattr(config, "ADMIN_IDS", [])
        monkeypatch.setattr(config, "MORNING_BRIEF_TIME", "07:30")

        bot = self._make_bot()
        # 6:00 — well before 07:30 window
        now = _make_dt(6, 0)

        from services.scheduler_parts.notification_check import check_all_notifications

        state = {"status": "OFF", "current_fuel": "200.0"}

        with (
            patch("services.scheduler_parts.notification_check.now_kiev", return_value=now),
            patch("services.scheduler_parts.notification_check._build_daily_report_text", return_value="report"),
        ):
            await check_all_notifications(bot, state)

        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_daily_report_not_resent_if_db_key_set(self, monkeypatch):
        """Daily report must not be re-sent if DB key already has today's date."""
        db.register_user(100, "user")
        monkeypatch.setattr(config, "ADMIN_IDS", [])
        monkeypatch.setattr(config, "MORNING_BRIEF_TIME", "07:30")

        from services.scheduler_parts.notification_check import DAILY_REPORT_KEY
        db.set_state(DAILY_REPORT_KEY, "2024-01-15")  # already sent today

        bot = self._make_bot()
        now = _make_dt(7, 45)

        from services.scheduler_parts.notification_check import check_all_notifications

        state = {"status": "OFF", "current_fuel": "200.0"}

        with (
            patch("services.scheduler_parts.notification_check.now_kiev", return_value=now),
            patch("services.scheduler_parts.notification_check._build_daily_report_text", return_value="report"),
        ):
            await check_all_notifications(bot, state)

        bot.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# B. Persistent idempotent send state
# ---------------------------------------------------------------------------


class TestDailyReportIdempotency:
    """Daily report uses DB-persisted state so restarts don't cause double-sends."""

    def _make_bot(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(chat=MagicMock(id=1), message_id=1))
        return bot

    @pytest.mark.asyncio
    async def test_db_key_written_after_send(self, monkeypatch):
        """After sending the daily report, the sent date must be persisted in DB."""
        db.register_user(100, "user")
        monkeypatch.setattr(config, "ADMIN_IDS", [])
        monkeypatch.setattr(config, "MORNING_BRIEF_TIME", "07:30")

        bot = self._make_bot()
        now = _make_dt(7, 31)

        from services.scheduler_parts.notification_check import check_all_notifications, DAILY_REPORT_KEY

        state = {"status": "OFF", "current_fuel": "200.0"}

        with (
            patch("services.scheduler_parts.notification_check.now_kiev", return_value=now),
            patch("services.scheduler_parts.notification_check._build_daily_report_text", return_value="report"),
        ):
            await check_all_notifications(bot, state)

        stored = db.get_state_value(DAILY_REPORT_KEY, "")
        assert stored == "2024-01-15", f"DB key should store today's date, got {stored!r}"

    @pytest.mark.asyncio
    async def test_no_resend_after_restart_within_window(self, monkeypatch):
        """If DB shows daily report already sent today, in-memory restart doesn't trigger resend."""
        db.register_user(100, "user")
        monkeypatch.setattr(config, "ADMIN_IDS", [])
        monkeypatch.setattr(config, "MORNING_BRIEF_TIME", "07:30")

        from services.scheduler_parts.notification_check import DAILY_REPORT_KEY
        db.set_state(DAILY_REPORT_KEY, "2024-01-15")  # already sent

        bot = self._make_bot()
        now = _make_dt(7, 50)  # still within the window

        from services.scheduler_parts.notification_check import check_all_notifications

        state = {"status": "OFF", "current_fuel": "200.0"}

        with (
            patch("services.scheduler_parts.notification_check.now_kiev", return_value=now),
            patch("services.scheduler_parts.notification_check._build_daily_report_text", return_value="report"),
        ):
            await check_all_notifications(bot, state)

        # Should NOT resend because DB key says already sent today
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_on_new_day_even_if_yesterday_key_exists(self, monkeypatch):
        """If DB key has yesterday's date, the daily report should be sent today."""
        db.register_user(100, "user")
        monkeypatch.setattr(config, "ADMIN_IDS", [])
        monkeypatch.setattr(config, "MORNING_BRIEF_TIME", "07:30")

        from services.scheduler_parts.notification_check import DAILY_REPORT_KEY
        db.set_state(DAILY_REPORT_KEY, "2024-01-14")  # yesterday

        bot = self._make_bot()
        now = _make_dt(7, 31)

        from services.scheduler_parts.notification_check import check_all_notifications

        state = {"status": "OFF", "current_fuel": "200.0"}

        with (
            patch("services.scheduler_parts.notification_check.now_kiev", return_value=now),
            patch("services.scheduler_parts.notification_check._build_daily_report_text", return_value="report"),
        ):
            await check_all_notifications(bot, state)

        bot.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# C. Quiet-hours wrap-around fix
# ---------------------------------------------------------------------------


class TestQuietHoursWrapAround:
    """_is_quiet_time must correctly handle overnight quiet hours (22:00–08:00)."""

    def _quiet_time(self, user_id, start_str, end_str, current_hhmm):
        from services.scheduler_parts.notification_check import _is_quiet_time

        now = MagicMock()
        now.strftime = lambda fmt: current_hhmm

        with patch(
            "services.scheduler_parts.notification_check.get_quiet_hours",
            return_value=(start_str, end_str),
        ):
            return _is_quiet_time(user_id, now)

    def test_overnight_start_in_evening(self):
        """22:00-08:00 quiet hours: 23:00 should be quiet."""
        assert self._quiet_time(1, "22:00", "08:00", "23:00") is True

    def test_overnight_early_morning(self):
        """22:00-08:00 quiet hours: 01:00 should be quiet."""
        assert self._quiet_time(1, "22:00", "08:00", "01:00") is True

    def test_overnight_just_before_end(self):
        """22:00-08:00 quiet hours: 07:59 should be quiet."""
        assert self._quiet_time(1, "22:00", "08:00", "07:59") is True

    def test_overnight_at_end_not_quiet(self):
        """22:00-08:00 quiet hours: 08:00 should NOT be quiet (end is exclusive)."""
        assert self._quiet_time(1, "22:00", "08:00", "08:00") is False

    def test_overnight_midday_not_quiet(self):
        """22:00-08:00 quiet hours: 12:00 should NOT be quiet."""
        assert self._quiet_time(1, "22:00", "08:00", "12:00") is False

    def test_normal_range_inside(self):
        """08:00-20:00 quiet hours: 10:00 should be quiet."""
        assert self._quiet_time(1, "08:00", "20:00", "10:00") is True

    def test_normal_range_outside(self):
        """08:00-20:00 quiet hours: 21:00 should NOT be quiet."""
        assert self._quiet_time(1, "08:00", "20:00", "21:00") is False

    def test_no_quiet_hours_configured(self):
        """If no quiet hours configured, never quiet."""
        from services.scheduler_parts.notification_check import _is_quiet_time

        now = MagicMock()
        now.strftime = lambda fmt: "02:00"
        with patch(
            "services.scheduler_parts.notification_check.get_quiet_hours",
            return_value=(None, None),
        ):
            assert _is_quiet_time(1, now) is False


# ---------------------------------------------------------------------------
# D. _should_notify logging and skip reasons
# ---------------------------------------------------------------------------


class TestShouldNotifySkipLogging:
    """_should_notify must return False and log when preference/quiet/debounce suppresses."""

    def _call_should_notify(self, user_id, notif_type, now_mock, *, pref=True, quiet=False, debounced=False):
        from services.scheduler_parts.notification_check import _should_notify

        with (
            patch("services.scheduler_parts.notification_check.is_notification_enabled", return_value=pref),
            patch("services.scheduler_parts.notification_check._is_quiet_time", return_value=quiet),
            patch("services.scheduler_parts.notification_check._is_debounced", return_value=debounced),
        ):
            return _should_notify(user_id, notif_type, now_mock)

    def test_preference_disabled_returns_false(self, caplog):
        import logging
        with caplog.at_level(logging.DEBUG, logger="services.scheduler_parts.notification_check"):
            result = self._call_should_notify(1, "fuel_warning", MagicMock(), pref=False)
        assert result is False

    def test_quiet_hours_returns_false(self, caplog):
        import logging
        with caplog.at_level(logging.DEBUG, logger="services.scheduler_parts.notification_check"):
            result = self._call_should_notify(1, "daily_report", MagicMock(), quiet=True)
        assert result is False

    def test_debounced_returns_false(self, caplog):
        import logging
        with caplog.at_level(logging.DEBUG, logger="services.scheduler_parts.notification_check"):
            result = self._call_should_notify(1, "fuel_warning", MagicMock(), debounced=True)
        assert result is False

    def test_critical_ignores_quiet_hours(self):
        """Critical notifications must NOT be suppressed by quiet hours."""
        from services.scheduler_parts.notification_check import _should_notify

        with (
            patch("services.scheduler_parts.notification_check.is_notification_enabled", return_value=True),
            patch("services.scheduler_parts.notification_check._is_quiet_time", return_value=True),
            patch("services.scheduler_parts.notification_check._is_debounced", return_value=False),
        ):
            # fuel_critical is category=critical
            result = _should_notify(1, "fuel_critical", MagicMock())
        assert result is True

    def test_all_conditions_pass_returns_true(self):
        result = self._call_should_notify(1, "fuel_warning", MagicMock(), pref=True, quiet=False, debounced=False)
        assert result is True


# ---------------------------------------------------------------------------
# E. Daily report content blocks
# ---------------------------------------------------------------------------


class TestDailyReportContent:
    """_build_daily_report_text must include all required operational blocks."""

    def test_content_includes_generator_status(self, monkeypatch):
        monkeypatch.setattr(config, "MORNING_BRIEF_TIME", "07:30")
        monkeypatch.setattr(config, "FUEL_CONSUMPTION", 5.0)
        monkeypatch.setattr(config, "EMERGENCY_FUEL_CONSUMPTION", 4.0)
        monkeypatch.setattr(config, "FUEL_ALERT_THRESHOLD_L", 40.0)
        monkeypatch.setattr(config, "OIL_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "SPARK_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "MAINTENANCE_INTERVAL", 200)

        now = _make_dt(7, 31)

        from services.scheduler_parts.notification_check import _build_daily_report_text

        with (
            patch("services.scheduler_parts.notification_check.db.get_schedule", return_value={}),
            patch("services.scheduler_parts.notification_check.db.get_state", return_value={"current_fuel": "50.0", "status": "OFF"}),
            patch("services.scheduler_parts.notification_check.db.get_active_generator", return_value="main"),
            patch(
                "services.scheduler_parts.notification_check.get_maintenance_stats",
                return_value={"oil_needed": 80.0, "spark_needed": 60.0, "maintenance_needed": 150.0},
            ),
            patch("services.scheduler_parts.notification_check.yesterday_shifts_summary", return_value="—"),
        ):
            txt = _build_daily_report_text(now, "2024-01-15")

        assert "Генератор" in txt, "Text must include generator status section"
        assert "Основний" in txt, "Active generator label must be present"
        assert "Паливо" in txt, "Text must include fuel section"
        assert "50.0" in txt, "Fuel level must be shown"
        assert "Техобслуговування" in txt, "Text must include maintenance section"

    def test_content_has_separate_maintenance_countdowns(self, monkeypatch):
        """Must have separate lines for oil, spark plugs, and planned service."""
        monkeypatch.setattr(config, "FUEL_CONSUMPTION", 5.0)
        monkeypatch.setattr(config, "EMERGENCY_FUEL_CONSUMPTION", 4.0)
        monkeypatch.setattr(config, "FUEL_ALERT_THRESHOLD_L", 40.0)
        monkeypatch.setattr(config, "OIL_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "SPARK_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "MAINTENANCE_INTERVAL", 200)

        now = _make_dt(7, 31)

        from services.scheduler_parts.notification_check import _build_daily_report_text

        with (
            patch("services.scheduler_parts.notification_check.db.get_schedule", return_value={}),
            patch("services.scheduler_parts.notification_check.db.get_state", return_value={"current_fuel": "80.0", "status": "ON"}),
            patch("services.scheduler_parts.notification_check.db.get_active_generator", return_value="main"),
            patch(
                "services.scheduler_parts.notification_check.get_maintenance_stats",
                return_value={"oil_needed": 20.0, "spark_needed": 45.0, "maintenance_needed": 120.0},
            ),
            patch("services.scheduler_parts.notification_check.yesterday_shifts_summary", return_value="—"),
        ):
            txt = _build_daily_report_text(now, "2024-01-15")

        assert "мастила" in txt.lower(), "Must have oil change countdown"
        assert "свічок" in txt.lower(), "Must have spark plug countdown"
        assert "планового" in txt.lower(), "Must have planned service countdown"

    def test_content_critical_warnings_when_overdue(self, monkeypatch):
        """Must show overdue warning when maintenance is at 0."""
        monkeypatch.setattr(config, "FUEL_CONSUMPTION", 5.0)
        monkeypatch.setattr(config, "EMERGENCY_FUEL_CONSUMPTION", 4.0)
        monkeypatch.setattr(config, "FUEL_ALERT_THRESHOLD_L", 40.0)
        monkeypatch.setattr(config, "OIL_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "SPARK_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "MAINTENANCE_INTERVAL", 200)

        now = _make_dt(7, 31)

        from services.scheduler_parts.notification_check import _build_daily_report_text

        with (
            patch("services.scheduler_parts.notification_check.db.get_schedule", return_value={}),
            patch("services.scheduler_parts.notification_check.db.get_state", return_value={"current_fuel": "20.0", "status": "OFF"}),
            patch("services.scheduler_parts.notification_check.db.get_active_generator", return_value="main"),
            patch(
                "services.scheduler_parts.notification_check.get_maintenance_stats",
                return_value={"oil_needed": 0.0, "spark_needed": 0.0, "maintenance_needed": 0.0},
            ),
            patch("services.scheduler_parts.notification_check.yesterday_shifts_summary", return_value="—"),
        ):
            txt = _build_daily_report_text(now, "2024-01-15")

        assert "прострочен" in txt.lower() or "Нагадування" in txt, "Must contain overdue warnings"
        assert "Низький рівень палива" in txt, "Low fuel warning must appear when fuel < threshold"

    def test_content_with_emergency_generator(self, monkeypatch):
        """When emergency generator is active, label and rates must reflect that."""
        monkeypatch.setattr(config, "FUEL_CONSUMPTION", 5.0)
        monkeypatch.setattr(config, "EMERGENCY_FUEL_CONSUMPTION", 3.5)
        monkeypatch.setattr(config, "FUEL_ALERT_THRESHOLD_L", 40.0)
        monkeypatch.setattr(config, "OIL_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "SPARK_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "MAINTENANCE_INTERVAL", 200)

        now = _make_dt(7, 31)

        from services.scheduler_parts.notification_check import _build_daily_report_text

        with (
            patch("services.scheduler_parts.notification_check.db.get_schedule", return_value={}),
            patch("services.scheduler_parts.notification_check.db.get_state", return_value={"current_fuel": "70.0", "status": "ON"}),
            patch("services.scheduler_parts.notification_check.db.get_active_generator", return_value="emergency"),
            patch(
                "services.scheduler_parts.notification_check.get_maintenance_stats",
                return_value={"oil_needed": 50.0, "spark_needed": 50.0, "maintenance_needed": 150.0},
            ),
            patch("services.scheduler_parts.notification_check.yesterday_shifts_summary", return_value="—"),
        ):
            txt = _build_daily_report_text(now, "2024-01-15")

        assert "Аварійний" in txt, "Emergency generator label must appear in daily report"

    def test_content_includes_yesterday_summary(self, monkeypatch):
        monkeypatch.setattr(config, "FUEL_CONSUMPTION", 5.0)
        monkeypatch.setattr(config, "EMERGENCY_FUEL_CONSUMPTION", 4.0)
        monkeypatch.setattr(config, "FUEL_ALERT_THRESHOLD_L", 40.0)
        monkeypatch.setattr(config, "OIL_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "SPARK_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "MAINTENANCE_INTERVAL", 200)

        now = _make_dt(7, 31)
        from services.scheduler_parts.notification_check import _build_daily_report_text

        with (
            patch("services.scheduler_parts.notification_check.db.get_schedule", return_value={}),
            patch("services.scheduler_parts.notification_check.db.get_state", return_value={"current_fuel": "80.0", "status": "OFF"}),
            patch("services.scheduler_parts.notification_check.db.get_active_generator", return_value="main"),
            patch(
                "services.scheduler_parts.notification_check.get_maintenance_stats",
                return_value={"oil_needed": 90.0, "spark_needed": 90.0, "maintenance_needed": 190.0},
            ),
            patch(
                "services.scheduler_parts.notification_check.yesterday_shifts_summary",
                return_value="🌅 Ранок: 07:00–09:30",
            ),
        ):
            txt = _build_daily_report_text(now, "2024-01-15")

        assert "Вчорашні зміни" in txt
        assert "07:00–09:30" in txt

    def test_outage_schedule_with_ranges(self, monkeypatch):
        """Outage ranges must appear correctly in the daily report."""
        monkeypatch.setattr(config, "FUEL_CONSUMPTION", 5.0)
        monkeypatch.setattr(config, "EMERGENCY_FUEL_CONSUMPTION", 4.0)
        monkeypatch.setattr(config, "FUEL_ALERT_THRESHOLD_L", 40.0)
        monkeypatch.setattr(config, "OIL_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "SPARK_CHANGE_INTERVAL", 100)
        monkeypatch.setattr(config, "MAINTENANCE_INTERVAL", 200)

        # Schedule: hours 9, 10, 11 are outage
        schedule = {h: (1 if h in (9, 10, 11) else 0) for h in range(24)}

        now = _make_dt(7, 31)
        from services.scheduler_parts.notification_check import _build_daily_report_text

        with (
            patch("services.scheduler_parts.notification_check.db.get_schedule", return_value=schedule),
            patch("services.scheduler_parts.notification_check.db.get_state", return_value={"current_fuel": "80.0", "status": "OFF"}),
            patch("services.scheduler_parts.notification_check.db.get_active_generator", return_value="main"),
            patch(
                "services.scheduler_parts.notification_check.get_maintenance_stats",
                return_value={"oil_needed": 90.0, "spark_needed": 90.0, "maintenance_needed": 190.0},
            ),
            patch("services.scheduler_parts.notification_check.yesterday_shifts_summary", return_value="—"),
        ):
            txt = _build_daily_report_text(now, "2024-01-15")

        assert "09:00 - 12:00" in txt, "Outage range 09:00-12:00 must appear in daily report"
        assert "3 год" in txt, "Total offline hours must be shown"


# ---------------------------------------------------------------------------
# F. Daily report window (MORNING_BRIEF_TIME-based)
# ---------------------------------------------------------------------------


class TestDailyWeeklyReportWindow:
    """daily_report fires once in the 60-minute window after MORNING_BRIEF_TIME."""

    @pytest.mark.asyncio
    async def test_daily_report_fires_within_brief_window(self, monkeypatch):
        """daily_report must be sent when within the MORNING_BRIEF_TIME window."""
        user_id = 500
        db.register_user(user_id, "Test User")
        monkeypatch.setattr(config, "ADMIN_IDS", [])
        monkeypatch.setattr(config, "MORNING_BRIEF_TIME", "07:30")

        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(chat=MagicMock(id=1), message_id=1))

        # now=07:35 — within the 60-minute window starting at 07:30
        now_mock = _make_dt(7, 35)

        from services.scheduler_parts.notification_check import check_all_notifications

        state = {"status": "OFF", "current_fuel": "200.0"}

        with (
            patch("services.scheduler_parts.notification_check.now_kiev", return_value=now_mock),
            patch(
                "services.scheduler_parts.notification_check._build_daily_report_text",
                return_value="📊 Щоденний звіт (test)",
            ),
        ):
            await check_all_notifications(bot, state)

        bot.send_message.assert_called()
        call_texts = [str(c) for c in bot.send_message.call_args_list]
        assert any("Щоденний звіт" in t for t in call_texts), "daily_report must be sent"

    @pytest.mark.asyncio
    async def test_daily_report_not_fired_outside_brief_window(self, monkeypatch):
        """daily_report must NOT be sent outside the MORNING_BRIEF_TIME window."""
        user_id = 501
        db.register_user(user_id, "Test User")
        monkeypatch.setattr(config, "ADMIN_IDS", [])
        monkeypatch.setattr(config, "MORNING_BRIEF_TIME", "07:30")

        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(chat=MagicMock(id=1), message_id=1))

        # Hour 10 — well outside the 07:30 + 60min window
        now_mock = _make_dt(10, 0)

        from services.scheduler_parts.notification_check import check_all_notifications

        state = {"status": "OFF", "current_fuel": "200.0"}

        with (
            patch("services.scheduler_parts.notification_check.now_kiev", return_value=now_mock),
            patch(
                "services.scheduler_parts.notification_check._build_daily_report_text",
                return_value="📊 Щоденний звіт (test)",
            ),
        ):
            await check_all_notifications(bot, state)

        call_texts = [str(c) for c in bot.send_message.call_args_list]
        daily_calls = [t for t in call_texts if "Щоденний звіт" in t]
        assert len(daily_calls) == 0, "daily_report must NOT fire outside MORNING_BRIEF_TIME window"


# ---------------------------------------------------------------------------
# G. Regression: Admin receives critical notifications
# ---------------------------------------------------------------------------


class TestAdminNotificationRegression:
    """Regression tests ensuring admins receive notifications they should get."""

    @pytest.mark.asyncio
    async def test_admin_receives_fuel_critical_notification(self, monkeypatch):
        """Admins must receive fuel_critical alerts (they are the intended audience)."""
        admin_id = 999
        monkeypatch.setattr(config, "ADMIN_IDS", [admin_id])
        db.register_user(admin_id, "Admin")

        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(chat=MagicMock(id=1), message_id=1))

        from services.scheduler_parts.notification_check import check_all_notifications
        from database.api.notifications import set_user_preference
        set_user_preference(admin_id, "fuel_critical", True)

        state = {"status": "ON", "current_fuel": "10.0"}  # < 15L triggers fuel_critical
        now_mock = _make_dt(12, 0)

        with patch("services.scheduler_parts.notification_check.now_kiev", return_value=now_mock):
            await check_all_notifications(bot, state)

        assert bot.send_message.call_count >= 1, "Admin must receive fuel_critical notification"
        call_texts = [str(c) for c in bot.send_message.call_args_list]
        assert any("КРИТИЧНО" in t or "Паливо" in t for t in call_texts), "Must mention fuel critical"

    @pytest.mark.asyncio
    async def test_daily_report_regression_admin_included(self, monkeypatch):
        """Regression test: daily report must be sent to admins, not just regular users."""
        admin_id = 777
        regular_user_id = 888
        monkeypatch.setattr(config, "ADMIN_IDS", [admin_id])
        db.register_user(admin_id, "Admin")
        db.register_user(regular_user_id, "User")

        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(chat=MagicMock(id=1), message_id=1))

        monkeypatch.setattr(config, "MORNING_BRIEF_TIME", "07:30")
        now = _make_dt(7, 35)

        from services.scheduler_parts.notification_check import check_all_notifications

        state = {"status": "OFF", "current_fuel": "200.0"}

        with (
            patch("services.scheduler_parts.notification_check.now_kiev", return_value=now),
            patch("services.scheduler_parts.notification_check._build_daily_report_text", return_value="report text"),
        ):
            await check_all_notifications(bot, state)

        sent_ids = {c.kwargs.get("chat_id") or c.args[0] for c in bot.send_message.call_args_list}
        assert admin_id in sent_ids, (
            f"REGRESSION: admin {admin_id} was not sent the daily report. "
            "Admins must receive the daily report too."
        )
