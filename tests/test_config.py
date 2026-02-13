"""Tests for config.py with corrected assertions."""
import pytest
from pathlib import Path

from config import (
    DatabaseSettings,
    RedisSettings,
    SheetsSettings,
    LoggingSettings,
    WorkScheduleSettings,
    MaintenanceSettings,
    FuelSettings,
    AccessSettings,
    Settings,
)


class TestDatabaseSettings:
    """Tests for DatabaseSettings."""

    def test_default_backend(self):
        """Test default database backend and path."""
        db = DatabaseSettings()
        assert db.backend == "sqlite"
        assert db.sqlite_path == "generator.db"

    def test_postgres_backend(self):
        """Test PostgreSQL backend configuration."""
        db = DatabaseSettings(
            backend="postgres",
            postgres_dsn="postgresql://user:pass@localhost/db"
        )
        assert db.backend == "postgres"
        assert "localhost" in db.postgres_dsn


class TestRedisSettings:
    """Tests for RedisSettings."""

    def test_default_disabled(self):
        """Test Redis is disabled by default."""
        redis = RedisSettings()
        assert redis.enabled is False

    def test_enabled_with_url(self):
        """Test Redis enabled with URL."""
        redis = RedisSettings(
            enabled=True,
            url="redis://localhost:6379/0"
        )
        assert redis.enabled is True
        assert "localhost" in redis.url


class TestSheetsSettings:
    """Tests for SheetsSettings."""

    def test_default_service_account_path(self):
        """Test default service account path."""
        sheets = SheetsSettings(
            sheet_id_prod="test_prod",
            sheet_id_test="test_test"
        )
        assert sheets.service_account_path == Path("service_account.json")


class TestLoggingSettings:
    """Tests for LoggingSettings."""

    def test_default_log_level(self):
        """Test default log level is INFO."""
        logging = LoggingSettings()
        assert logging.log_level == "INFO"

    def test_custom_log_level(self):
        """Test custom log level is normalized to uppercase."""
        logging = LoggingSettings(log_level="debug")
        assert logging.log_level == "DEBUG"


class TestWorkScheduleSettings:
    """Tests for WorkScheduleSettings."""

    def test_default_timezone(self):
        """Test default timezone is Europe/Kyiv."""
        schedule = WorkScheduleSettings()
        assert schedule.timezone == "Europe/Kyiv"

    def test_default_times(self):
        """Test default work times."""
        schedule = WorkScheduleSettings()
        assert schedule.work_start_time == "07:30"
        assert schedule.work_end_time == "20:30"
        assert schedule.morning_brief_time == "07:30"


class TestMaintenanceSettings:
    """Tests for MaintenanceSettings."""

    def test_default_intervals(self):
        """Test default maintenance intervals."""
        maint = MaintenanceSettings()
        assert maint.oil_change_interval == 100
        assert maint.spark_change_interval == 100
        assert maint.maintenance_interval == 300
        assert maint.oil_limit == 100


class TestFuelSettings:
    """Tests for FuelSettings."""

    def test_default_consumption(self):
        """Test default fuel consumption is 5.3."""
        fuel = FuelSettings()
        assert fuel.fuel_consumption == 5.3
        assert fuel.emergency_fuel_consumption == 5.3

    def test_fuel_rate_alias(self):
        """Test fuel_rate is an alias for fuel_consumption."""
        fuel = FuelSettings(fuel_rate=6.0)
        assert fuel.fuel_consumption == 6.0

    def test_custom_emergency_consumption(self):
        """Test custom emergency fuel consumption."""
        fuel = FuelSettings(
            fuel_consumption=1.0,
            emergency_fuel_consumption=1.5
        )
        assert fuel.fuel_consumption == 1.0
        assert fuel.emergency_fuel_consumption == 1.5


class TestAccessSettings:
    """Tests for AccessSettings."""

    def test_parse_admin_ids(self, monkeypatch):
        """Test parsing admin IDs from environment."""
        monkeypatch.setenv("ADMINS", "123456789,987654321")
        access = AccessSettings()
        assert access.get_admin_ids() == [123456789, 987654321]

    def test_default_bot_status(self):
        """Test default bot status."""
        access = AccessSettings(admins="1")
        assert access.bot_status == "ON"


class TestMainSettings:
    """Tests for main Settings class."""

    def test_settings_initialized(self, monkeypatch):
        """Test Settings can be initialized."""
        monkeypatch.setenv("BOT_TOKEN", "test_token")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        settings = Settings()
        assert settings.bot_token == "test_token"

    def test_is_test_mode_property(self, monkeypatch):
        """Test is_test_mode property."""
        monkeypatch.setenv("BOT_TOKEN", "test_token")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        
        settings_test = Settings(mode="TEST")
        assert settings_test.is_test_mode is True
        
        settings_prod = Settings(mode="PROD")
        assert settings_prod.is_test_mode is False

    def test_kyiv_tz_property(self, monkeypatch):
        """Test kyiv_tz property returns timezone object."""
        monkeypatch.setenv("BOT_TOKEN", "test_token")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        settings = Settings()
        assert "Europe/Kyiv" in str(settings.kyiv_tz)


class TestBackwardCompatibility:
    """Tests for backward compatibility exports."""

    def test_uppercase_exports(self):
        """Test uppercase module-level exports for backward compatibility."""
        from config import BOT_TOKEN, DB_BACKEND, FUEL_CONSUMPTION, IS_TEST_MODE
        
        assert BOT_TOKEN is not None
        assert DB_BACKEND in ["sqlite", "postgres"]
        assert FUEL_CONSUMPTION > 0
        assert isinstance(IS_TEST_MODE, bool)
