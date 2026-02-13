"""Tests for Pydantic-based config module."""
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from config import (
    ADMIN_IDS,
    BOT_TOKEN,
    DB_BACKEND,
    FUEL_CONSUMPTION,
    IS_TEST_MODE,
    KYIV,
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
    """Test DatabaseSettings model."""

    def test_default_backend(self):
        """Test default database backend."""
        db = DatabaseSettings()
        assert db.backend == "sqlite"
        assert db.sqlite_path == "generator.db"

    def test_postgres_requires_dsn(self):
        """Test that postgres backend requires DSN."""
        with pytest.raises(ValidationError, match="POSTGRES_DSN is required"):
            DatabaseSettings(backend="postgres")

    def test_pool_size_validation(self):
        """Test connection pool size validation."""
        with pytest.raises(ValidationError):
            DatabaseSettings(pg_pool_min_size=0)  # Should be >= 1

        with pytest.raises(ValidationError):
            DatabaseSettings(pg_pool_max_size=-5)  # Should be >= 1


class TestRedisSettings:
    """Test RedisSettings model."""

    def test_default_disabled(self):
        """Test Redis is disabled by default."""
        redis = RedisSettings()
        assert redis.enabled is False

    def test_enabled_requires_url(self):
        """Test that enabled Redis requires URL."""
        with pytest.raises(ValidationError, match="REDIS_URL is required"):
            RedisSettings(enabled=True, url="")

    def test_default_url(self):
        """Test default Redis URL."""
        redis = RedisSettings()
        assert redis.url == "redis://localhost:6379/0"


class TestSheetsSettings:
    """Test SheetsSettings model."""

    def test_requires_sheet_ids(self, monkeypatch):
        """Test that sheet IDs are required."""
        monkeypatch.delenv("SHEET_ID_PROD", raising=False)
        monkeypatch.delenv("SHEET_ID_TEST", raising=False)

        with pytest.raises(ValidationError):
            SheetsSettings()

    def test_service_account_path(self):
        """Test service account path is converted to Path."""
        sheets = SheetsSettings(
            sheet_id_prod="prod_id",
            sheet_id_test="test_id",
            service_account_path="custom_account.json",
        )
        assert isinstance(sheets.service_account_path, Path)
        assert sheets.service_account_path == Path("custom_account.json")


class TestLoggingSettings:
    """Test LoggingSettings model."""

    def test_default_log_level(self):
        """Test default log level is INFO."""
        logging = LoggingSettings()
        assert logging.log_level == "INFO"

    def test_log_level_normalization(self):
        """Test log level is normalized to uppercase."""
        logging = LoggingSettings(log_level="debug")
        assert logging.log_level == "DEBUG"

    def test_invalid_log_level(self):
        """Test invalid log level is rejected."""
        with pytest.raises(ValidationError):
            LoggingSettings(log_level="INVALID")

    def test_log_size_validation(self):
        """Test log size must be >= 1024."""
        with pytest.raises(ValidationError):
            LoggingSettings(log_max_bytes=100)  # Too small


class TestWorkScheduleSettings:
    """Test WorkScheduleSettings model."""

    def test_default_timezone(self):
        """Test default timezone is Europe/Kyiv."""
        schedule = WorkScheduleSettings()
        assert schedule.timezone == "Europe/Kyiv"

    def test_invalid_timezone_fallback(self):
        """Test invalid timezone falls back to UTC."""
        schedule = WorkScheduleSettings(timezone="Invalid/Timezone")
        assert schedule.timezone == "UTC"

    def test_time_format_validation(self):
        """Test time format validation."""
        with pytest.raises(ValidationError, match="Time must be in HH:MM format"):
            WorkScheduleSettings(work_start_time="25:00")  # Invalid hour

        with pytest.raises(ValidationError):
            WorkScheduleSettings(work_end_time="12:70")  # Invalid minutes

        with pytest.raises(ValidationError):
            WorkScheduleSettings(morning_brief_time="not-a-time")

    def test_valid_times(self):
        """Test valid time formats are accepted."""
        schedule = WorkScheduleSettings(
            work_start_time="07:30",
            work_end_time="20:30",
            morning_brief_time="08:00",
        )
        assert schedule.work_start_time == "07:30"
        assert schedule.work_end_time == "20:30"
        assert schedule.morning_brief_time == "08:00"


class TestMaintenanceSettings:
    """Test MaintenanceSettings model."""

    def test_default_intervals(self):
        """Test default maintenance intervals."""
        maint = MaintenanceSettings()
        assert maint.oil_change_interval == 100
        assert maint.spark_change_interval == 100
        assert maint.maintenance_interval == 300

    def test_intervals_must_be_positive(self):
        """Test intervals must be > 0."""
        with pytest.raises(ValidationError):
            MaintenanceSettings(oil_change_interval=0)

        with pytest.raises(ValidationError):
            MaintenanceSettings(spark_change_interval=-10)

    def test_oil_limit_compat(self):
        """Test OIL_LIMIT backward compatibility."""
        maint = MaintenanceSettings(oil_change_interval=50)
        assert maint.oil_limit == 50  # Should match oil_change_interval


class TestFuelSettings:
    """Test FuelSettings model."""

    def test_default_consumption(self):
        """Test default fuel consumption."""
        fuel = FuelSettings()
        assert fuel.fuel_consumption == 5.3

    def test_fuel_rate_alias(self):
        """Test FUEL_RATE is alias for FUEL_CONSUMPTION."""
        fuel = FuelSettings(fuel_rate=0.8)
        assert fuel.fuel_consumption == 0.8

    def test_emergency_defaults_to_main(self):
        """Test emergency consumption defaults to main consumption."""
        fuel = FuelSettings(fuel_consumption=1.5)
        assert fuel.emergency_fuel_consumption == 1.5

    def test_emergency_can_be_different(self):
        """Test emergency consumption can differ from main."""
        fuel = FuelSettings(fuel_consumption=1.0, emergency_fuel_consumption=1.2)
        assert fuel.fuel_consumption == 1.0
        assert fuel.emergency_fuel_consumption == 1.2

    def test_consumption_must_be_positive(self):
        """Test fuel consumption must be > 0."""
        with pytest.raises(ValidationError):
            FuelSettings(fuel_consumption=0)

        with pytest.raises(ValidationError):
            FuelSettings(fuel_consumption=-1.5)


class TestAccessSettings:
    """Test AccessSettings model."""

    def test_parse_admin_ids(self):
        """Test parsing admin IDs from string."""
        access = AccessSettings(admins="123,456,789")
        assert access.get_admin_ids() == [123, 456, 789]

    def test_parse_whitelist(self):
        """Test parsing whitelist IDs from string."""
        access = AccessSettings(admins="123", users="111,222")
        assert access.get_whitelist() == [111, 222]

    def test_invalid_id_format(self):
        """Test invalid ID format is rejected."""
        with pytest.raises(ValidationError, match="Invalid user ID list format"):
            AccessSettings(admins="not-a-number")

    def test_registration_open_property(self):
        """Test registration_open property."""
        access_on = AccessSettings(admins="123", bot_status="ON")
        assert access_on.registration_open is True

        access_off = AccessSettings(admins="123", bot_status="OFF")
        assert access_off.registration_open is False


class TestMainSettings:
    """Test main Settings model."""

    def test_settings_initialized(self):
        """Test global settings instance is initialized."""
        assert settings is not None
        assert isinstance(settings, Settings)

    def test_is_test_mode_property(self):
        """Test is_test_mode property."""
        assert settings.is_test_mode is True  # Running in test env
        assert settings.mode == "TEST"

    def test_sheet_id_property(self):
        """Test sheet_id property returns correct ID based on mode."""
        # In test mode, should return test sheet ID
        assert settings.sheet_id == settings.sheets.sheet_id_test

    def test_kyiv_tz_property(self):
        """Test kyiv_tz returns ZoneInfo object."""
        from zoneinfo import ZoneInfo

        assert isinstance(settings.kyiv_tz, ZoneInfo)

    def test_validate_all_method(self):
        """Test validate_all method (backward compat)."""
        # Should not raise
        settings.validate_all()


class TestBackwardCompatibility:
    """Test backward compatibility exports."""

    def test_bot_token_export(self):
        """Test BOT_TOKEN is exported."""
        assert BOT_TOKEN is not None
        assert isinstance(BOT_TOKEN, str)

    def test_admin_ids_export(self):
        """Test ADMIN_IDS is exported as list."""
        assert isinstance(ADMIN_IDS, list)
        assert all(isinstance(x, int) for x in ADMIN_IDS)

    def test_db_backend_export(self):
        """Test DB_BACKEND is exported."""
        assert DB_BACKEND in ["sqlite", "postgres"]

    def test_fuel_consumption_export(self):
        """Test FUEL_CONSUMPTION is exported as float."""
        assert isinstance(FUEL_CONSUMPTION, float)
        assert FUEL_CONSUMPTION > 0

    def test_is_test_mode_export(self):
        """Test IS_TEST_MODE is exported as bool."""
        assert isinstance(IS_TEST_MODE, bool)
        assert IS_TEST_MODE is True

    def test_kyiv_export(self):
        """Test KYIV timezone is exported."""
        from zoneinfo import ZoneInfo

        assert isinstance(KYIV, ZoneInfo)


class TestValidateEnvFunction:
    """Test validate_env backward compatibility function."""

    def test_validate_env_exists(self):
        """Test validate_env function exists."""
        from config import validate_env

        # Should not raise in test environment
        validate_env()


class TestEnvBoolHelper:
    """Test _env_bool helper function."""

    def test_env_bool_exists(self):
        """Test _env_bool helper exists for backward compat."""
        from config import _env_bool

        # Test with actual env vars
        os.environ["TEST_BOOL_VAR"] = "1"
        assert _env_bool("TEST_BOOL_VAR") is True

        os.environ["TEST_BOOL_VAR"] = "0"
        assert _env_bool("TEST_BOOL_VAR") is False

        # Test default
        assert _env_bool("NONEXISTENT", default=True) is True

        # Cleanup
        del os.environ["TEST_BOOL_VAR"]


@pytest.mark.unit
class TestPydanticValidation:
    """Test Pydantic validation features."""

    def test_missing_required_field(self, monkeypatch):
        """Test missing required field raises error."""
        monkeypatch.delenv("BOT_TOKEN", raising=False)
        monkeypatch.delenv("ADMINS", raising=False)

        with pytest.raises(ValidationError):
            Settings()

    def test_type_validation(self):
        """Test type validation works."""
        with pytest.raises(ValidationError):
            FuelSettings(fuel_consumption="not-a-number")  # type: ignore

    def test_constraint_validation(self):
        """Test field constraints are enforced."""
        # gt=0 constraint
        with pytest.raises(ValidationError):
            MaintenanceSettings(oil_change_interval=-5)

        # ge=1 constraint
        with pytest.raises(ValidationError):
            DatabaseSettings(pg_pool_min_size=0)
