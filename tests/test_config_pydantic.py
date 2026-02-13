"""Tests for Pydantic-based configuration."""
import os
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from config import (
    AccessSettings,
    DatabaseSettings,
    FuelSettings,
    LoggingSettings,
    MaintenanceSettings,
    RedisSettings,
    Settings,
    SheetsSettings,
    WorkScheduleSettings,
    settings,
)


class TestDatabaseSettings:
    """Test DatabaseSettings validation."""

    def test_default_values(self):
        """Test default database configuration."""
        db = DatabaseSettings()
        assert db.backend == "sqlite"
        assert db.sqlite_path == "generator.db"
        assert db.pg_pool_min_size == 2
        assert db.pg_pool_max_size == 10

    def test_postgres_requires_dsn(self):
        """Test that postgres backend requires DSN."""
        with pytest.raises(ValidationError, match="POSTGRES_DSN is required"):
            DatabaseSettings(backend="postgres", postgres_dsn="")

    def test_backend_normalization(self):
        """Test that backend is normalized to lowercase."""
        db = DatabaseSettings(backend="SQLite")
        assert db.backend == "sqlite"

    def test_pool_constraints(self):
        """Test connection pool size constraints."""
        # Minimum values
        db = DatabaseSettings(pg_pool_min_size=1, pg_pool_max_size=1)
        assert db.pg_pool_min_size == 1
        assert db.pg_pool_max_size == 1

        # Invalid values should raise
        with pytest.raises(ValidationError):
            DatabaseSettings(pg_pool_min_size=0)


class TestRedisSettings:
    """Test RedisSettings validation."""

    def test_default_values(self):
        """Test default Redis configuration."""
        redis = RedisSettings()
        assert redis.enabled is False
        assert redis.url == "redis://localhost:6379/0"

    def test_enabled_requires_url(self):
        """Test that enabled Redis requires URL."""
        with pytest.raises(ValidationError, match="REDIS_URL is required"):
            RedisSettings(enabled=True, url="")

    def test_disabled_doesnt_require_url(self):
        """Test that disabled Redis doesn't require URL."""
        redis = RedisSettings(enabled=False, url="")
        assert redis.enabled is False


class TestSheetsSettings:
    """Test SheetsSettings validation."""

    def test_requires_sheet_ids(self, monkeypatch):
        """Test that sheet IDs are required."""
        monkeypatch.setenv("SHEET_ID_PROD", "test_prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test_test")
        sheets = SheetsSettings()
        assert sheets.sheet_id_prod == "test_prod"
        assert sheets.sheet_id_test == "test_test"

    def test_service_account_path(self):
        """Test service account path as Path object."""
        sheets = SheetsSettings(
            sheet_id_prod="test",
            sheet_id_test="test",
            service_account_path="custom_account.json",
        )
        assert isinstance(sheets.service_account_path, Path)
        assert str(sheets.service_account_path) == "custom_account.json"


class TestLoggingSettings:
    """Test LoggingSettings validation."""

    def test_default_values(self):
        """Test default logging configuration."""
        log = LoggingSettings()
        assert log.log_level == "INFO"
        assert log.log_file == "bot.log"
        assert log.log_max_bytes == 10485760  # 10MB
        assert log.log_backup_count == 5

    def test_log_level_normalization(self):
        """Test that log level is normalized to uppercase."""
        log = LoggingSettings(log_level="debug")
        assert log.log_level == "DEBUG"

    def test_log_level_validation(self):
        """Test that only valid log levels are accepted."""
        with pytest.raises(ValidationError):
            LoggingSettings(log_level="INVALID")

    def test_size_constraints(self):
        """Test log file size constraints."""
        # Minimum 1KB
        log = LoggingSettings(log_max_bytes=1024)
        assert log.log_max_bytes == 1024

        # Below minimum should fail
        with pytest.raises(ValidationError):
            LoggingSettings(log_max_bytes=512)


class TestWorkScheduleSettings:
    """Test WorkScheduleSettings validation."""

    def test_default_values(self):
        """Test default schedule configuration."""
        schedule = WorkScheduleSettings()
        assert schedule.timezone == "Europe/Kyiv"
        assert schedule.work_start_time == "07:30"
        assert schedule.work_end_time == "20:30"

    def test_timezone_validation(self):
        """Test timezone validation."""
        # Valid timezone
        schedule = WorkScheduleSettings(timezone="America/New_York")
        assert schedule.timezone == "America/New_York"

        # Invalid timezone falls back to UTC
        schedule = WorkScheduleSettings(timezone="Invalid/Timezone")
        assert schedule.timezone == "UTC"

    def test_time_format_validation(self):
        """Test time format validation (HH:MM)."""
        # Valid time
        schedule = WorkScheduleSettings(work_start_time="09:00")
        assert schedule.work_start_time == "09:00"

        # Invalid formats should raise
        with pytest.raises(ValidationError, match="HH:MM"):
            WorkScheduleSettings(work_start_time="9:00")  # Single digit hour

        with pytest.raises(ValidationError):
            WorkScheduleSettings(work_start_time="25:00")  # Invalid hour

        with pytest.raises(ValidationError):
            WorkScheduleSettings(work_start_time="12:60")  # Invalid minute

        with pytest.raises(ValidationError):
            WorkScheduleSettings(work_start_time="not-a-time")


class TestMaintenanceSettings:
    """Test MaintenanceSettings validation."""

    def test_default_values(self):
        """Test default maintenance configuration."""
        maint = MaintenanceSettings()
        assert maint.oil_change_interval == 100
        assert maint.spark_change_interval == 100
        assert maint.maintenance_interval == 300

    def test_positive_intervals(self):
        """Test that intervals must be positive."""
        # Valid positive values
        maint = MaintenanceSettings(oil_change_interval=50)
        assert maint.oil_change_interval == 50

        # Zero should fail
        with pytest.raises(ValidationError):
            MaintenanceSettings(oil_change_interval=0)

        # Negative should fail
        with pytest.raises(ValidationError):
            MaintenanceSettings(spark_change_interval=-10)

    def test_oil_limit_compatibility(self):
        """Test OIL_LIMIT backward compatibility."""
        maint = MaintenanceSettings(oil_limit=150)
        assert maint.oil_limit == 150

        # When oil_limit not set, uses oil_change_interval
        maint = MaintenanceSettings(oil_change_interval=200)
        assert maint.oil_limit == 200


class TestFuelSettings:
    """Test FuelSettings validation."""

    def test_default_values(self):
        """Test default fuel configuration."""
        fuel = FuelSettings()
        assert fuel.fuel_consumption == 5.3
        assert fuel.fuel_alert_threshold == 40.0
        assert fuel.fuel_alert_cooldown_min == 60

    def test_fuel_rate_alias(self):
        """Test FUEL_RATE alias for FUEL_CONSUMPTION."""
        fuel = FuelSettings(fuel_rate=0.8)
        assert fuel.fuel_consumption == 0.8

    def test_emergency_fuel_default(self):
        """Test that emergency fuel defaults to main consumption."""
        fuel = FuelSettings(fuel_consumption=0.9)
        assert fuel.emergency_fuel_consumption == 0.9

        # Explicit emergency value takes precedence
        fuel = FuelSettings(fuel_consumption=0.9, emergency_fuel_consumption=1.2)
        assert fuel.emergency_fuel_consumption == 1.2

    def test_positive_values(self):
        """Test that fuel values must be positive."""
        with pytest.raises(ValidationError):
            FuelSettings(fuel_consumption=0)

        with pytest.raises(ValidationError):
            FuelSettings(fuel_consumption=-1.5)


class TestAccessSettings:
    """Test AccessSettings validation."""

    def test_admin_ids_parsing(self, monkeypatch):
        """Test admin IDs parsing from comma-separated string."""
        monkeypatch.setenv("ADMINS", "123,456,789")
        access = AccessSettings()
        admin_ids = access.get_admin_ids()
        assert admin_ids == [123, 456, 789]

    def test_whitelist_parsing(self):
        """Test whitelist parsing."""
        access = AccessSettings(admins="123", users="111,222")
        whitelist = access.get_whitelist()
        assert whitelist == [111, 222]

    def test_empty_lists(self):
        """Test handling of empty ID lists."""
        access = AccessSettings(admins="123", users="")
        assert access.get_whitelist() == []

    def test_invalid_id_format(self, monkeypatch):
        """Test that invalid ID formats are rejected."""
        with pytest.raises(ValidationError, match="Invalid user ID"):
            AccessSettings(admins="123,not-a-number,456")

    def test_registration_open_property(self):
        """Test registration_open property."""
        access = AccessSettings(admins="123", bot_status="ON")
        assert access.registration_open is True

        access = AccessSettings(admins="123", bot_status="OFF")
        assert access.registration_open is False


class TestMainSettings:
    """Test main Settings class."""

    def test_is_test_mode(self):
        """Test test mode detection."""
        # Current settings should be in TEST mode (from conftest.py)
        assert settings.is_test_mode is True

    def test_sheet_id_selection(self, monkeypatch):
        """Test sheet ID selection based on mode."""
        monkeypatch.setenv("MODE", "TEST")
        monkeypatch.setenv("SHEET_ID_PROD", "prod_id")
        monkeypatch.setenv("SHEET_ID_TEST", "test_id")
        monkeypatch.setenv("ADMINS", "123")
        monkeypatch.setenv("BOT_TOKEN", "test_token")

        test_settings = Settings()
        assert test_settings.sheet_id == "test_id"

        monkeypatch.setenv("MODE", "PROD")
        prod_settings = Settings()
        assert prod_settings.sheet_id == "prod_id"

    def test_kyiv_tz_property(self):
        """Test timezone property returns ZoneInfo."""
        tz = settings.kyiv_tz
        assert isinstance(tz, ZoneInfo)

    def test_print_config(self, capsys):
        """Test configuration printing."""
        settings.print_config()
        captured = capsys.readouterr()
        assert "ПОТОЧНА КОНФІГУРАЦІЯ" in captured.out
        assert "TEST" in captured.out or "PROD" in captured.out


class TestBackwardCompatibility:
    """Test backward compatibility exports."""

    def test_core_exports(self):
        """Test core configuration exports."""
        from config import BOT_TOKEN, IS_TEST_MODE, MODE

        assert isinstance(BOT_TOKEN, str)
        assert isinstance(MODE, str)
        assert isinstance(IS_TEST_MODE, bool)

    def test_database_exports(self):
        """Test database configuration exports."""
        from config import DB_BACKEND, PG_POOL_MAX_SIZE, SQLITE_PATH

        assert DB_BACKEND in ["sqlite", "postgres"]
        assert isinstance(SQLITE_PATH, str)
        assert isinstance(PG_POOL_MAX_SIZE, int)

    def test_fuel_exports(self):
        """Test fuel configuration exports."""
        from config import EMERGENCY_FUEL_CONSUMPTION, FUEL_CONSUMPTION

        assert isinstance(FUEL_CONSUMPTION, float)
        assert FUEL_CONSUMPTION > 0
        assert isinstance(EMERGENCY_FUEL_CONSUMPTION, float)

    def test_admin_ids_export(self):
        """Test ADMIN_IDS export."""
        from config import ADMIN_IDS

        assert isinstance(ADMIN_IDS, list)
        assert all(isinstance(x, int) for x in ADMIN_IDS)

    def test_timezone_exports(self):
        """Test timezone exports."""
        from config import KYIV, TIMEZONE

        assert isinstance(TIMEZONE, str)
        assert isinstance(KYIV, ZoneInfo)

    def test_validate_env_function(self):
        """Test backward compatible validate_env() function."""
        from config import validate_env

        # Should not raise
        validate_env()

    def test_env_bool_helper(self):
        """Test _env_bool helper function."""
        from config import _env_bool

        os.environ["TEST_BOOL"] = "1"
        assert _env_bool("TEST_BOOL") is True

        os.environ["TEST_BOOL"] = "false"
        assert _env_bool("TEST_BOOL") is False

        assert _env_bool("NONEXISTENT", default=True) is True

        del os.environ["TEST_BOOL"]


@pytest.mark.unit
class TestValidationErrors:
    """Test that validation errors are properly raised."""

    def test_missing_required_field(self, monkeypatch):
        """Test that missing required fields raise errors."""
        # Clear BOT_TOKEN
        monkeypatch.delenv("BOT_TOKEN", raising=False)

        with pytest.raises(ValidationError, match="BOT_TOKEN"):
            Settings()

    def test_invalid_mode(self, monkeypatch):
        """Test that invalid mode is rejected."""
        monkeypatch.setenv("MODE", "INVALID")
        monkeypatch.setenv("BOT_TOKEN", "test")
        monkeypatch.setenv("ADMINS", "123")
        monkeypatch.setenv("SHEET_ID_PROD", "test")
        monkeypatch.setenv("SHEET_ID_TEST", "test")

        with pytest.raises(ValidationError):
            Settings()

    def test_postgres_without_dsn_exits(self, monkeypatch):
        """Test that postgres backend without DSN causes validation error."""
        monkeypatch.setenv("DB_BACKEND", "postgres")
        monkeypatch.setenv("POSTGRES_DSN", "")

        with pytest.raises(ValidationError):
            DatabaseSettings()


@pytest.mark.integration
class TestConfigIntegration:
    """Integration tests for configuration loading."""

    def test_load_from_env_file(self, tmp_path, monkeypatch):
        """Test loading configuration from .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            """BOT_TOKEN=test_token_123
MODE=TEST
ADMINS=111,222,333
SHEET_ID_PROD=prod_sheet
SHEET_ID_TEST=test_sheet
FUEL_CONSUMPTION=0.8
"""
        )

        monkeypatch.chdir(tmp_path)

        # This would load from the .env file in tmp_path
        # But since Settings is already instantiated globally,
        # we just test that it doesn't crash
        test_settings = Settings(_env_file=str(env_file))
        assert test_settings.bot_token == "test_token_123"
        assert test_settings.mode == "TEST"

    def test_env_override(self, monkeypatch):
        """Test that environment variables override .env file."""
        # Environment variables should have precedence
        monkeypatch.setenv("BOT_TOKEN", "override_token")
        monkeypatch.setenv("MODE", "PROD")
        monkeypatch.setenv("ADMINS", "999")
        monkeypatch.setenv("SHEET_ID_PROD", "test")
        monkeypatch.setenv("SHEET_ID_TEST", "test")

        test_settings = Settings()
        assert test_settings.bot_token == "override_token"
        assert test_settings.mode == "PROD"
